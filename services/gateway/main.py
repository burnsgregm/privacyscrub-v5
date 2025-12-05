import os
import json
import uuid
import httpx
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import Response
from google.cloud import firestore, tasks_v2, storage

app = FastAPI(title="PrivacyScrub V5 Gateway")

# Configuration
PROJECT_ID = os.environ.get("GCP_PROJECT_ID")
# Construct bucket name (Standard V5 convention)
BUCKET_NAME = f"{PROJECT_ID}-media-v5"

ORCHESTRATOR_URL = os.environ.get("ORCHESTRATOR_URL")
WORKER_URL = os.environ.get("WORKER_URL")
QUEUE_REGION = "us-central1"
QUEUE_NAME = "privacyscrub-video-queue"

# Initialize Google Cloud Clients
db = firestore.Client()
tasks_client = tasks_v2.CloudTasksClient()
storage_client = storage.Client()

@app.post("/v1/video")
async def submit_video(
    file: UploadFile = File(...), 
    webhook_url: str = Form(None)
):
    if not ORCHESTRATOR_URL:
        raise HTTPException(status_code=500, detail="Orchestrator URL not configured")

    job_id = str(uuid.uuid4())

    # 1. Upload Video to Cloud Storage (The Missing Step!)
    try:
        bucket = storage_client.bucket(BUCKET_NAME)
        blob_path = f"input/{job_id}/original.mp4"
        blob = bucket.blob(blob_path)
        
        # Upload from spool (FastAPI handles memory/disk spooling)
        # We rewind the file just in case
        await file.seek(0)
        # Note: 'upload_from_file' expects a synchronous file-like object.
        # FastAPI's SpooledTemporaryFile works perfectly here.
        blob.upload_from_file(file.file, content_type=file.content_type)
        print(f"Uploaded video to gs://{BUCKET_NAME}/{blob_path}")
        
    except Exception as e:
        print(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload video: {str(e)}")

    # 2. Create Job Record
    doc_ref = db.collection("jobs").document(job_id)
    doc_ref.set({
        "status": "QUEUED",
        "webhook_url": webhook_url,
        "filename": file.filename,
        "created_at": firestore.SERVER_TIMESTAMP,
        "chunks_total": 0,
        "chunks_completed": 0
    })

    # 3. Dispatch to Orchestrator
    parent = tasks_client.queue_path(PROJECT_ID, QUEUE_REGION, QUEUE_NAME)
    
    payload = {
        "job_id": job_id,
        "filename": file.filename
    }
    
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{ORCHESTRATOR_URL}/internal/ingest",
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(payload).encode(),
        }
    }

    try:
        tasks_client.create_task(request={"parent": parent, "task": task})
    except Exception as e:
        # In a real app, delete the uploaded file here to cleanup
        raise HTTPException(status_code=500, detail=f"Failed to enqueue job: {str(e)}")

    return {"job_id": job_id, "status": "QUEUED"}

@app.post("/v1/anonymize-image")
async def anonymize_image(
    file: UploadFile = File(...), 
    profile: str = Form("NONE"),
    mode: str = Form("blur"),
    target_logos: bool = Form(False),
    target_text: bool = Form(False)
):
    if not WORKER_URL:
        return Response(content=b"Error: WORKER_URL not configured.", status_code=500)
    
    options = json.dumps({
        "mode": mode,
        "target_logos": target_logos,
        "target_text": target_text
    })
    
    image_bytes = await file.read()
    filename = file.filename if file.filename else "image.jpg"
    
    async with httpx.AsyncClient() as client:
        data = {"profile": profile, "options": options}
        files = {'file': (filename, image_bytes, 'image/jpeg')}
        
        try:
            response = await client.post(
                f"{WORKER_URL}/internal/process-image", 
                data=data,
                files=files,
                timeout=60.0 
            )
            return Response(content=response.content, media_type="image/jpeg", status_code=response.status_code)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=500, detail=f"Worker contact failed: {exc}")

@app.get("/v1/jobs/{job_id}")
def get_status(job_id: str):
    doc = db.collection("jobs").document(job_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Job not found")
    return doc.to_dict()