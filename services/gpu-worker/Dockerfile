# Use PyTorch with CUDA support
FROM pytorch/pytorch:2.1.0-cuda12.1-cudnn8-runtime

WORKDIR /app

# 1. Install System Dependencies
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ffmpeg libsm6 libxext6 libgl1 wget build-essential

# 2. Install Python Dependencies
RUN pip install "numpy<2" ultralytics moviepy opencv-python-headless google-cloud-storage google-cloud-firestore fastapi uvicorn python-multipart huggingface_hub easyocr scipy

# --- COPY PRE-DOWNLOADED MODELS ---
# A. General Model (YOLOv8 Extra Large)
COPY model_cache/yolov8x.pt .

# B. Specialists
COPY model_cache/yolov8n-face.pt .
COPY model_cache/license_plate_detector.pt .

# C. OCR
COPY model_cache/easyocr_models /root/.EasyOCR/model/ 

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]