import os
import json
import subprocess
import glob
import requests
from fastapi import FastAPI, HTTPException, Body
from google.cloud import storage, firestore, tasks_v2

app = FastAPI()

# Config
PROJECT_ID = os.environ.get("GCP_PROJECT_ID")
BUCKET_NAME_ENV = os.environ.get("GCS_BUCKET_NAME")
BUCKET_NAME = BUCKET_NAME_ENV if BUCKET_NAME_ENV else f"{PROJECT_ID}-media-v5"
WORKER_URL = os.environ.get("WORKER_URL")
QUEUE_REGION = "us-central1"
QUEUE_NAME = "privacyscrub-video-queue"

storage_client = storage.Client()
db = firestore.Client()
tasks_client = tasks_v2.CloudTasksClient()

@app.post("/internal/ingest")
async def ingest_video(payload: dict = Body(...)):
    """
    Downloads the video, determines if splitting is needed, and dispatches tasks.
    """
    job_id = payload.get("job_id")
    
    # 1. Update Status
    job_ref = db.collection("jobs").document(job_id)
    job_ref.update({"status": "CHUNKING"})

    # 2. Download Original Video
    bucket = storage_client.bucket(BUCKET_NAME)
    blob_path = f"input/{job_id}/original.mp4"
    local_path = f"/tmp/{job_id}_original.mp4"
    
    blob = bucket.blob(blob_path)
    if not blob.exists():
        print(f"Error: Video not found at {blob_path}")
        job_ref.update({"status": "FAILED", "error_message": "Input video not found"})
        return {"status": "error"}
        
    blob.download_to_filename(local_path)

    # 3. Analyze Duration
    try:
        # Run ffprobe to get duration in seconds
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration", 
            "-of", "default=noprint_wrappers=1:nokey=1", local_path
        ]
        duration = float(subprocess.check_output(cmd).decode().strip())
        print(f"Video Duration: {duration} seconds")
    except Exception as e:
        print(f"Probe failed: {e}")
        duration = 0 # Fallback

    # 4. Logic: Bypass split if short
    CHUNK_DURATION = 300 # 5 minutes
    chunks_to_dispatch = [] # List of filenames

    if duration > 0 and duration < CHUNK_DURATION:
        print("Video is short. Bypassing split.")
        # Treat the original file as the single chunk
        # Worker expects chunks named chunk_XXX.mp4
        chunk_name = "chunk_000.mp4"
        dest_blob = bucket.blob(f"input/{job_id}/{chunk_name}")
        
        # We upload the original file to the chunk path
        dest_blob.upload_from_filename(local_path)
        chunks_to_dispatch.append(chunk_name)
        
    else:
        print("Video is long. Splitting...")
        output_pattern = f"/tmp/{job_id}_chunk_%03d.mp4"
        
        # Run FFMPEG Segment
        subprocess.run([
            "ffmpeg", "-y", "-i", local_path, "-c", "copy", "-map", "0",
            "-f", "segment", "-segment_time", str(CHUNK_DURATION), 
            "-reset_timestamps", "1", output_pattern
        ], check=True)
        
        # Collect and Upload Chunks
        generated_files = sorted(glob.glob(f"/tmp/{job_id}_chunk_*.mp4"))
        for fpath in generated_files:
            fname = os.path.basename(fpath).replace(f"{job_id}_", "") # clean name
            # Upload to GCS
            bucket.blob(f"input/{job_id}/{fname}").upload_from_filename(fpath)
            chunks_to_dispatch.append(fname)
            os.remove(fpath) # cleanup tmp

    # 5. Update Job State
    total_chunks = len(chunks_to_dispatch)
    job_ref.update({"chunks_total": total_chunks})

    # 6. Dispatch to GPU Worker
    parent = tasks_client.queue_path(PROJECT_ID, QUEUE_REGION, QUEUE_NAME)

    for i, chunk_name in enumerate(chunks_to_dispatch):
        worker_payload = {
            "job_id": job_id,
            "chunk_name": chunk_name,
            "chunk_index": i
        }
        
        task = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": f"{WORKER_URL}/internal/process-chunk",
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(worker_payload).encode(),
            }
        }
        
        try:
            tasks_client.create_task(request={"parent": parent, "task": task})
        except Exception as e:
            print(f"Failed to dispatch chunk {i}: {e}")

    # Cleanup Original
    if os.path.exists(local_path): os.remove(local_path)

    return {"status": "dispatched", "chunks": total_chunks}

@app.post("/internal/stitch")
async def stitch_video(payload: dict = Body(...)):
    """Called when all chunks are done to finalize the video."""
    job_id = payload.get("job_id")
    
    # 1. Update Status
    db.collection("jobs").document(job_id).update({"status": "STITCHING"})

    # 2. Download Processed Chunks
    bucket = storage_client.bucket(BUCKET_NAME)
    blobs = list(bucket.list_blobs(prefix=f"output/{job_id}/"))
    
    # Filter for chunk_XXX.mp4 files only
    chunk_blobs = [b for b in blobs if "chunk_" in b.name and b.name.endswith(".mp4")]
    chunk_blobs.sort(key=lambda x: x.name) # Ensure correct order 000, 001...
    
    local_files = []
    
    # Create the concat list file for ffmpeg
    with open(f"/tmp/{job_id}_input.txt", "w") as f:
        for blob in chunk_blobs:
            local_file = f"/tmp/{os.path.basename(blob.name)}"
            blob.download_to_filename(local_file)
            local_files.append(local_file)
            f.write(f"file '{local_file}'\n")
    
    output_local = f"/tmp/{job_id}_final.mp4"
    
    # 3. Stitch with Metadata Stripping
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", 
        "-i", f"/tmp/{job_id}_input.txt", 
        "-map_metadata", "-1", # FR-IMG-03: Strip Metadata
        "-c", "copy", output_local
    ], check=True)

    # 4. Upload Final Video
    final_blob = bucket.blob(f"output/{job_id}/final.mp4")
    final_blob.upload_from_filename(output_local)
    
    # Generate public/signed URL (valid 1 hour)
    # Note: In production, consider signed URLs. For now, publicRead if bucket allows or authenticated.
    # We will assume signed URL for safety.
    try:
        output_url = final_blob.generate_signed_url(version="v4", expiration=3600, method="GET")
    except:
        # Fallback if service account lacks signToken permissions
        output_url = f"https://storage.googleapis.com/{BUCKET_NAME}/output/{job_id}/final.mp4"

    # 5. Finalize Job
    db.collection("jobs").document(job_id).update({
        "status": "COMPLETED",
        "output_url": output_url
    })
    
    # 6. Webhook Notification
    job_doc = db.collection("jobs").document(job_id).get()
    webhook_url = job_doc.to_dict().get("webhook_url")
    
    if webhook_url:
        try:
            print(f"Sending webhook to {webhook_url}...")
            requests.post(webhook_url, json={
                "job_id": job_id,
                "status": "COMPLETED",
                "output_url": output_url
            }, timeout=5)
        except Exception as e:
            print(f"Webhook failed: {e}")
            
    # Cleanup
    for f in local_files: 
        if os.path.exists(f): os.remove(f)
    if os.path.exists(output_local): os.remove(output_local)
    
    return {"status": "COMPLETED", "url": output_url}

@app.delete("/v1/jobs/{job_id}")
def delete_job(job_id: str):
    """Right to Erasure."""
    bucket = storage_client.bucket(BUCKET_NAME)
    blobs = list(bucket.list_blobs(prefix=f"input/{job_id}")) + \
            list(bucket.list_blobs(prefix=f"output/{job_id}"))
    for blob in blobs:
        blob.delete()
    
    db.collection("jobs").document(job_id).update({"status": "CANCELLED"})
    return {"status": "CANCELLED", "data": "erased"}