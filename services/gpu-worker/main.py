import os
import cv2
import numpy as np
import json
import requests
from fastapi import FastAPI, Body, UploadFile, File, Response, Form
from google.cloud import storage, firestore
from inference import PrivacyEngine
from config import get_config_for_profile

app = FastAPI()

# Initialize Engine (Loads YOLOv8 models + OCR)
engine = PrivacyEngine()

# Initialize Clients
storage_client = storage.Client()
db = firestore.Client()

# Configuration
PROJECT_ID = os.environ.get("GCP_PROJECT_ID")
BUCKET_NAME_ENV = os.environ.get("GCS_BUCKET_NAME")
# Fallback logic for local testing
BUCKET_NAME = BUCKET_NAME_ENV if BUCKET_NAME_ENV else f"{PROJECT_ID}-media-v5"

@app.post("/internal/process-image")
async def process_image_internal(
    file: UploadFile = File(...),
    profile: str = Form("NONE"),
    options: str = Form("{}") # JSON string of overrides
):
    """
    Synchronous image processing endpoint invoked by Gateway.
    """
    image_bytes = await file.read()
    
    # 1. Hydrate Config
    try:
        user_opts = json.loads(options)
    except json.JSONDecodeError:
        user_opts = {}

    cfg = get_config_for_profile(profile, user_opts)
    
    # 2. Decode
    np_arr = np.frombuffer(image_bytes, np.uint8)
    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if frame is None:
        return Response(content=b"Invalid image", status_code=400)
    
    # 3. Run Engine
    processed_frame = engine.detect_and_redact(frame, cfg)
    
    # 4. Encode and Return
    success, encoded = cv2.imencode('.jpg', processed_frame)
    if not success:
         return Response(content=b"Encoding failed", status_code=500)

    return Response(content=encoded.tobytes(), media_type="image/jpeg")

@app.post("/internal/process-chunk")
def process_chunk(payload: dict = Body(...)):
    """
    Asynchronous video chunk processing endpoint invoked by Orchestrator.
    """
    job_id = payload.get("job_id")
    chunk_name = payload.get("chunk_name")
    
    # 1. Update Job Status to PROCESSING
    job_ref = db.collection("jobs").document(job_id)
    job_ref.update({"status": "PROCESSING"})
    
    # 2. Fetch Job Config
    job_snap = job_ref.get()
    job_data = job_snap.to_dict()
    
    # Generate Config from Job settings stored in Firestore
    cfg = get_config_for_profile(
        job_data.get("profile", "NONE"),
        {
            "target_logos": job_data.get("target_logos", False),
            "target_text": job_data.get("target_text", False),
            "mode": job_data.get("mode", "blur")
        }
    )
    
    # 3. Download from GCS
    bucket = storage_client.bucket(BUCKET_NAME)
    
    # We assume Orchestrator put chunks in input/{job_id}/{chunk_name}
    blob_path = f"input/{job_id}/{chunk_name}"
    local_input = f"/tmp/{chunk_name}"
    local_output = f"/tmp/processed_{chunk_name}"
    
    blob = bucket.blob(blob_path)
    if blob.exists():
        blob.download_to_filename(local_input)
    else:
        # Mock for testing if file doesn't exist
        print(f"Warning: Blob {blob_path} not found. Creating dummy.")
        dummy = np.zeros((100,100,3), np.uint8)
        cv2.imwrite(local_input, dummy)
    
    # 4. Run Video Inference Loop
    cap = cv2.VideoCapture(local_input)
    if not cap.isOpened():
         print("Error opening video file")
         return {"status": "error", "message": "Could not open video"}

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    
    out = cv2.VideoWriter(local_output, cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))
    
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret: break
        
        # Run the detection engine
        processed_frame = engine.detect_and_redact(frame, cfg)
        out.write(processed_frame)
    
    cap.release()
    out.release()
    
    # 5. Upload Result
    output_blob_path = f"output/{job_id}/{chunk_name}"
    output_blob = bucket.blob(output_blob_path)
    output_blob.upload_from_filename(local_output)
    
    # 6. Cleanup Local Files
    if os.path.exists(local_input): os.remove(local_input)
    if os.path.exists(local_output): os.remove(local_output)
    
    # 7. Update Progress
    transaction = db.transaction()
    @firestore.transactional
    def update_progress(transaction, doc_ref):
        snapshot = doc_ref.get(transaction=transaction)
        new_count = snapshot.get("chunks_completed") + 1
        transaction.update(doc_ref, {"chunks_completed": new_count})
        return new_count, snapshot.get("chunks_total")

    completed, total = update_progress(transaction, job_ref)
    
    # 8. Check for Completion & Trigger Stitch
    if completed >= total:
        print(f"Job {job_id}: All {total} chunks completed. Triggering stitch.")
        
        # Trigger Stitching via Orchestrator
        orch_url = os.environ.get("ORCHESTRATOR_URL")
        if orch_url:
            try:
                # Fire and forget (timeout=1) so we don't block the worker while orchestrator stitches
                requests.post(
                    f"{orch_url}/internal/stitch", 
                    json={"job_id": job_id},
                    timeout=1 
                )
            except Exception as e:
                # We expect a ReadTimeout (intentional), or a connection error
                print(f"Stitch trigger sent (Msg: {e})")
        else:
            print("Error: ORCHESTRATOR_URL not set. Cannot stitch.")
    
    return {"status": "chunk_processed", "chunk": chunk_name}