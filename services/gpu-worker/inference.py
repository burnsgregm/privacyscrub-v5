import cv2
import numpy as np
import easyocr
from ultralytics import YOLO
from config import PrivacyConfig, AnonymizeMode

class PrivacyEngine:
    def __init__(self):
        print("Loading AI Models (V4 Spec)...")
        
        # 1. Main Brain: YOLOv8 EXTRA LARGE (Matches V4)
        self.general_model = YOLO('yolov8x.pt') 
        
        # 2. Specialist: Faces (V5 improvement kept)
        try:
            self.face_model = YOLO('yolov8n-face.pt')
        except:
            self.face_model = None

        # 3. Specialist: Plates (V5 improvement kept)
        try:
            self.plate_model = YOLO('license_plate_detector.pt')
        except:
            self.plate_model = None
            
        # 4. OCR
        self.ocr_reader = easyocr.Reader(['en'], gpu=False)

    def _get_ocr_boxes(self, frame, conf_thresh):
        boxes = []
        try:
            results = self.ocr_reader.readtext(frame)
            for (bbox, text, prob) in results:
                if prob >= conf_thresh:
                    x_coords = [p[0] for p in bbox]
                    y_coords = [p[1] for p in bbox]
                    boxes.append([min(x_coords), min(y_coords), max(x_coords), max(y_coords)])
        except Exception as e:
            print(f"OCR Error: {e}")
        return boxes

    def detect_and_redact(self, frame, config: PrivacyConfig):
        boxes_to_blur = []

        # --- A. GENERAL CONTEXT (YOLOv8-X) ---
        # V4 used default conf (usually 0.25 or 0.4)
        results_gen = self.general_model.predict(frame, conf=0.4, verbose=False)
        
        if results_gen and results_gen[0].boxes:
            for box in results_gen[0].boxes:
                cls_id = int(box.cls[0])
                xyxy = box.xyxy[0].cpu().numpy().astype(int)
                x1, y1, x2, y2 = xyxy

                # Class 0: Person (Backup for faces)
                # V4 Logic: Blur top 20%
                if cls_id == 0 and config.target_faces:
                    head_h = int((y2 - y1) * 0.20)
                    boxes_to_blur.append([x1, y1, x2, y1 + head_h])

                # Class 2,3,5,7: Vehicles (Heuristic for Plates)
                # V4 Logic: Blur bottom 25% (See Cell 5, PlateDetector)
                if cls_id in [2, 3, 5, 7] and config.target_plates and config.enable_heuristics:
                    bumper_h = int((y2 - y1) * 0.25) 
                    boxes_to_blur.append([x1, y2 - bumper_h, x2, y2])
                
                # Logos (Backpack/Suitcase/Handbag)
                if cls_id in [24, 26, 28] and config.target_logos:
                    boxes_to_blur.append(xyxy)

        # --- B. FACE DETECTION (Dedicated) ---
        if config.target_faces and self.face_model:
            results_face = self.face_model.predict(frame, conf=0.4, verbose=False)
            if results_face and results_face[0].boxes:
                for box in results_face[0].boxes:
                    boxes_to_blur.append(box.xyxy[0].cpu().numpy().astype(int))

        # --- C. PLATE DETECTION (Dedicated) ---
        if config.target_plates and self.plate_model:
            results_plate = self.plate_model.predict(frame, conf=0.15, verbose=False)
            if results_plate and results_plate[0].boxes:
                for box in results_plate[0].boxes:
                    boxes_to_blur.append(box.xyxy[0].cpu().numpy().astype(int))

        # --- D. OCR (Matches V4 TextDetector) ---
        # V4 ran this if target_text was True.
        # We also trigger it if heuristics are on, to catch text-heavy plates.
        if config.target_text or (config.target_plates and config.enable_heuristics):
            boxes_to_blur.extend(self._get_ocr_boxes(frame, config.confidence_threshold))

        # --- E. RENDER ---
        frame_out = frame.copy()
        h, w, _ = frame.shape
        
        for box in boxes_to_blur:
            x1, y1, x2, y2 = map(int, box)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            
            roi = frame_out[y1:y2, x1:x2]
            if roi.size == 0: continue
            
            if config.mode == AnonymizeMode.BLUR:
                roi = cv2.GaussianBlur(roi, (99, 99), 30)
                frame_out[y1:y2, x1:x2] = roi
            elif config.mode == AnonymizeMode.BLACK_BOX:
                cv2.rectangle(frame_out, (x1, y1), (x2, y2), (0, 0, 0), -1)
            elif config.mode == AnonymizeMode.PIXELATE:
                small = cv2.resize(roi, (max(1, (x2-x1)//10), max(1, (y2-y1)//10)))
                frame_out[y1:y2, x1:x2] = cv2.resize(small, (x2-x1, y2-y1), interpolation=cv2.INTER_NEAREST)

        return frame_out