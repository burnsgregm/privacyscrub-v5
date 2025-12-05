import os
import shutil
import sys
import easyocr
from ultralytics import YOLO
from huggingface_hub import hf_hub_download

# --- CONFIGURATION ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TARGET_DIR = os.path.join(SCRIPT_DIR, "../services/gpu-worker/model_cache")

print(f"Targeting build context: {TARGET_DIR}")

if os.path.exists(TARGET_DIR):
    shutil.rmtree(TARGET_DIR)
os.makedirs(TARGET_DIR, exist_ok=True)

try:
    # 1. General Model: YOLOv8-X (Extra Large - MATCHING V4 SPEC)
    print("1/4: Downloading YOLOv8-X (V4 Standard)...")
    YOLO('yolov8x.pt') 
    shutil.move('yolov8x.pt', os.path.join(TARGET_DIR, 'yolov8x.pt'))

    # 2. Face Model (Keeping this as it's better than V4 heuristic)
    print("2/4: Downloading Face Model...")
    file_path = hf_hub_download(repo_id='arnabdhar/YOLOv8-Face-Detection', filename='model.pt')
    shutil.copy(file_path, os.path.join(TARGET_DIR, 'yolov8n-face.pt'))

    # 3. Plate Model (Direct detection)
    print("3/4: Downloading Plate Model...")
    file_path = hf_hub_download(repo_id='yasirfaizahmed/license-plate-object-detection', filename='best.pt')
    shutil.copy(file_path, os.path.join(TARGET_DIR, 'license_plate_detector.pt'))

    # 4. OCR
    print("4/4: Downloading OCR models...")
    reader = easyocr.Reader(['en'], gpu=False) 
    source_dir = os.path.expanduser('~/.EasyOCR/model')
    ocr_target_dir = os.path.join(TARGET_DIR, 'easyocr_models')
    os.makedirs(ocr_target_dir, exist_ok=True)
    for filename in os.listdir(source_dir):
        shutil.copy(os.path.join(source_dir, filename), ocr_target_dir)

    print("\n✅ Download Complete (YOLOv8-X Enabled).")

except Exception as e:
    print(f"\n❌ Error: {e}")
    sys.exit(1)