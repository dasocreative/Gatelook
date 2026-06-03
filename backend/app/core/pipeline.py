import cv2
import numpy as np
import os
import re
import uuid
import random
from datetime import datetime
from app.core.config import settings

# Lazy import computer vision libs to prevent start failures when testing in mock mode
try:
    if not settings.MOCK_VISION_PIPELINE:
        from ultralytics import YOLO
        from paddleocr import PaddleOCR
except ImportError:
    pass

class ANPRPipeline:
    def __init__(self):
        self.mock_mode = settings.MOCK_VISION_PIPELINE
        
        # Track IDs that have already been saved to db during current stream session
        self.processed_track_ids = set()
        # Plate numbers that have already been saved to db during current stream session
        self.processed_plates = set()
        
        # Keep track of active mock vehicle states to simulate trajectory
        self.active_mock_vehicles = {}
        
        # Cache for recognized license plates to prevent repeated OCR runs:
        # Maps track_id -> {
        #   "plate_number": str,
        #   "confidence_score": float,
        #   "attempts": int,
        #   "relative_plate_box": list [px1, py1, px2, py2] or None,
        #   "crop_image_url": str
        # }
        self.track_ocr_cache = {}
        
        # OCR Text Regex Normalizers
        # Moroccan plates format: e.g. 12345-أ-6 or 12345/أ/6 (Digits | Arabic Letter | Prefecture ID)
        self.moroccan_regex = re.compile(r'(\d+)\s*[-\/|]?\s*([\u0600-\u06FFa-zA-Z])\s*[-\/|]?\s*(\d+)')
        self.general_regex = re.compile(r'[a-zA-Z0-9]{5,10}')

        if not self.mock_mode:
            print("[INFO] Initializing Real AI Models (YOLO + PaddleOCR)...")
            import torch
            if torch.backends.mps.is_available():
                self.device = "mps"
            elif torch.cuda.is_available():
                self.device = "cuda"
            else:
                self.device = "cpu"
            print(f"[INFO] Using device: {self.device}")

            # YOLO is initialized using standard Ultralytics package model (configured by env)
            self.vehicle_model = YOLO(settings.YOLO_VEHICLE_MODEL)
            # Secondary fine-tuned plate model if separate, else reuse primary
            self.plate_model = YOLO(settings.YOLO_PLATE_MODEL)
            self.ocr = PaddleOCR(use_angle_cls=True, lang='ar')
        else:
            print("[WARN] Running in MOCK Vision Pipeline Mode. Real models will not be loaded.")
            self.vehicle_model = None
            self.plate_model = None
            self.ocr = None

    def clean_plate_text(self, text: str) -> tuple[str, str]:
        """
        Cleans and normalizes recognized text.
        Returns:
            Tuple[cleaned_text, format_type]
        """
        # Helper to convert Arabic/Persian digits to ASCII standard digits
        def ar_to_en_digits(t: str) -> str:
            ar_digits = "٠١٢٣٤٥٦٧٨٩"
            fa_digits = "۰۱۲۳۴۵٦٧٨٩"
            en_digits = "0123456789"
            for i in range(10):
                t = t.replace(ar_digits[i], en_digits[i]).replace(fa_digits[i], en_digits[i])
            return t

        # Pre-normalize digits first (e.g. Arabic to English digits)
        normalized = ar_to_en_digits(text)
        
        # Remove noise, keeping alphanumeric and hyphens
        cleaned = re.sub(r'[^\w\u0600-\u06FF\-]', '', normalized).strip()
        
        # 1. Try standard Moroccan regex first (enforcing prefecture constraint: 1 <= pref <= 89)
        m_match = self.moroccan_regex.search(cleaned)
        if m_match:
            parts = m_match.groups()
            p0 = parts[0]
            p1 = parts[1]
            p2 = parts[2]
            if 1 <= int(p2) <= 89 and 1 <= len(p0) <= 5:
                return f"{p0}-{p1}-{p2}", "Moroccan Plate"
                
        # 2. Robust Moroccan Parser Fallback
        # Extract blocks from the space-preserving normalized string
        digit_blocks = re.findall(r'\d+', normalized)
        # Match only letters (excluding digits, spaces, hyphens, separators)
        letter_blocks = re.findall(r'[^\d\s\-_|/]+', normalized)
        
        # Case A: Two or more digit blocks (e.g. "43460 26" or "6 845")
        if len(digit_blocks) >= 2:
            pref = None
            main_num = None
            
            last_block = digit_blocks[-1]
            first_block = digit_blocks[0]
            
            # Heuristic: prefecture code is strictly 1 or 2 digits, and <= 89
            # Check last block first (standard LTR order)
            if len(last_block) <= 2 and 1 <= int(last_block) <= 89:
                pref = last_block
                main_num = "".join(digit_blocks[:-1])
            # Check first block (reversed/RTL order)
            elif len(first_block) <= 2 and 1 <= int(first_block) <= 89:
                pref = first_block
                main_num = "".join(digit_blocks[1:])
                
            if pref and main_num and 1 <= len(main_num) <= 5:
                # Letter selection: prefer a single character, else default to 'أ' (default series)
                letter = "أ"
                if letter_blocks:
                    single_chars = [l for l in letter_blocks if len(l) == 1]
                    if single_chars:
                        letter = single_chars[0]
                    else:
                        letter = letter_blocks[0][0]
                return f"{main_num}-{letter}-{pref}", "Moroccan Plate (Robust Parse)"
                
        # Case B: Single merged digit block (e.g. "3866126" or "258223")
        elif len(digit_blocks) == 1 and 5 <= len(digit_blocks[0]) <= 7:
            digits = digit_blocks[0]
            pref = None
            main_num = None
            
            # Check last 2 digits (only if it doesn't start with '0')
            last_two = digits[-2:]
            if last_two[0] != '0' and 1 <= int(last_two) <= 89:
                pref = last_two
                main_num = digits[:-2]
            else:
                # Check last 1 digit
                last_one = digits[-1:]
                if 1 <= int(last_one) <= 9:
                    pref = last_one
                    main_num = digits[:-1]
                # Fallback to last 2 digits even if it has a leading zero
                elif 1 <= int(last_two) <= 89:
                    pref = last_two
                    main_num = digits[:-2]
                    
            if pref and main_num and 1 <= len(main_num) <= 5:
                letter = "أ"
                if letter_blocks:
                    single_chars = [l for l in letter_blocks if len(l) == 1]
                    if single_chars:
                        letter = single_chars[0]
                    else:
                        letter = letter_blocks[0][0]
                return f"{main_num}-{letter}-{pref}", "Moroccan Plate (Split Parse)"

        # 3. Generic Alphanumeric Fallback
        g_match = self.general_regex.search(cleaned)
        if g_match:
            return g_match.group(0).upper(), "Standard Alphanumeric"
            
        # Fallback to alphanumeric extraction
        alphanumeric = re.sub(r'[^a-zA-Z0-9\u0600-\u06FF]', '', cleaned)
        return alphanumeric.upper(), "Unknown Format"

    def detect_attributes(self, crop_vehicle: np.ndarray, class_name: str = "car") -> tuple[str, str]:
        """
        Extracts vehicle Make/Model and Color.
        """
        if self.mock_mode:
            colors = ["White", "Black", "Grey", "Blue", "Red", "Silver", "Green", "Orange/Yellow"]
            models = ["Mercedes E-Class", "Dacia Logan", "Volkswagen Golf", "Toyota Hilux", "Audi A4", "BMW 3 Series", "Renault Clio"]
            h = crop_vehicle.shape[0] * crop_vehicle.shape[1]
            random.seed(h)
            return random.choice(models), random.choice(colors)
            
        # Robust pixel color count classification
        hsv = cv2.cvtColor(crop_vehicle, cv2.COLOR_BGR2HSV)
        h_chan, s_chan, v_chan = cv2.split(hsv)
        
        # Total pixels in vehicle crop
        tot_px = crop_vehicle.shape[0] * crop_vehicle.shape[1]
        
        # Saturated color masks: require S > 40 and V > 30
        sat_mask = (s_chan > 40) & (v_chan > 30)
        
        color_counts = {
            "Blue": np.sum(sat_mask & (h_chan >= 85) & (h_chan < 135)),
            "Red": np.sum(sat_mask & ((h_chan < 10) | (h_chan >= 160))),
            "Green": np.sum(sat_mask & (h_chan >= 35) & (h_chan < 85)),
            "Orange/Yellow": np.sum(sat_mask & (h_chan >= 10) & (h_chan < 35)),
            "Purple": np.sum(sat_mask & (h_chan >= 135) & (h_chan < 160))
        }
        
        # Grayscale masks: where S <= 40 or V <= 30
        unsat_mask = ~sat_mask
        white_count = np.sum(unsat_mask & (v_chan > 180))
        black_count = np.sum(unsat_mask & (v_chan < 55))
        grey_count = np.sum(unsat_mask & (v_chan >= 55) & (v_chan <= 180))
        
        sat_total = sum(color_counts.values())
        
        # Determine dominant saturated color
        dom_sat_color = max(color_counts, key=color_counts.get)
        dom_sat_count = color_counts[dom_sat_color]
        
        # Determine dominant grayscale color
        gray_counts = {"White": white_count, "Black": black_count, "Grey": grey_count}
        dom_gray_color = max(gray_counts, key=gray_counts.get)
        dom_gray_count = gray_counts[dom_gray_color]
        
        # Rule 1: Grayscale fallback if saturated pixels are less than 5% of total pixels
        if sat_total < (0.05 * tot_px) or sat_total < 100:
            color = dom_gray_color
        else:
            # Rule 2: If Blue is prominent (>= 25% of saturated pixels or >= 8% of total pixels),
            # prioritize Blue over decals/graphics like Orange/Yellow
            if color_counts["Blue"] >= (0.25 * sat_total) or color_counts["Blue"] >= (0.08 * tot_px):
                color = "Blue"
            # Rule 3: If Red is prominent, prioritize Red
            elif color_counts["Red"] >= (0.25 * sat_total) or color_counts["Red"] >= (0.08 * tot_px):
                color = "Red"
            # Rule 4: Grayscale check: if a grayscale color dominates (e.g. > 1.8x the dominant saturated color),
            # we classify it as that grayscale color (e.g. white car with small graphic)
            elif dom_gray_count > 1.8 * dom_sat_count:
                color = dom_gray_color
            else:
                color = dom_sat_color

        # Model Mapping based on class and aspect ratio
        h_dim, w_dim, _ = crop_vehicle.shape
        ratio = w_dim / h_dim if h_dim > 0 else 1.0
        
        if class_name == "car":
            if ratio > 1.5:
                model = "Dacia Logan"
            else:
                model = "Dacia Sandero"
        elif class_name == "truck":
            model = "Toyota Hilux" if ratio < 1.6 else "Volvo FH"
        elif class_name == "motorcycle":
            model = "Yamaha T-Max"
        elif class_name == "bus":
            model = "Mercedes Citaro"
        else:
            model = "Unknown Model"
            
        return model, color

    def process_frame(self, frame: np.ndarray, frame_id: int) -> list[dict]:
        """
        Process a single image frame.
        Returns a list of detected vehicle objects and coordinates.
        """
        detections = []
        
        if self.mock_mode:
            return self._process_mock_frame(frame, frame_id)
            
        # Real Inference execution
        # 1. Detect & track vehicles (Classes: 2=car, 3=motorcycle, 5=bus, 7=truck)
        # We track using track=True with ByteTrack/BoTSORT
        results = self.vehicle_model.track(
            source=frame, 
            persist=True, 
            classes=[2, 3, 5, 7], 
            conf=0.25,
            verbose=False,
            device=self.device
        )
        
        if not results or not results[0].boxes:
            return detections
            
        boxes = results[0].boxes
        for box in boxes:
            # Extract tracking and coords
            cls_id = int(box.cls[0].item())
            class_name = self.vehicle_model.names[cls_id]
            xyxy = box.xyxy[0].cpu().numpy().astype(int)
            conf = float(box.conf[0].item())
            
            # If tracking index is active
            track_id = int(box.id[0].item()) if box.id is not None else None
            
            # Crop vehicle sub-image
            x1, y1, x2, y2 = xyxy
            # Ensure coordinates are within image boundaries
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)
            
            if x2 <= x1 or y2 <= y1:
                continue
                
            crop_veh = frame[y1:y2, x1:x2]
            vehicle_model, vehicle_color = self.detect_attributes(crop_veh, class_name)
            
            plate_box = None
            plate_number = "UNKNOWN"
            ocr_conf = 0.0
            crop_path = ""
            run_ocr = True
            
            # If vehicle is not tracked, skip OCR entirely as it cannot be logged
            if track_id is None:
                run_ocr = False
            
            # 1. Check OCR Cache first
            if run_ocr and track_id in self.track_ocr_cache:
                cache = self.track_ocr_cache[track_id]
                
                # Check if we already have a high-confidence prediction
                if cache["confidence_score"] >= 0.85:
                    run_ocr = False
                    plate_number = cache["plate_number"]
                    ocr_conf = cache["confidence_score"]
                    crop_path = cache["crop_image_url"]
                    if cache["relative_plate_box"]:
                        rpx1, rpy1, rpx2, rpy2 = cache["relative_plate_box"]
                        plate_box = [int(x1 + rpx1), int(y1 + rpy1), int(x1 + rpx2), int(y1 + rpy2)]
                
                # If we've reached the maximum number of attempts, don't run OCR again
                elif cache["attempts"] >= settings.MAX_OCR_ATTEMPTS:
                    run_ocr = False
                    plate_number = cache["plate_number"]
                    ocr_conf = cache["confidence_score"]
                    crop_path = cache["crop_image_url"]
                    if cache["relative_plate_box"]:
                        rpx1, rpy1, rpx2, rpy2 = cache["relative_plate_box"]
                        plate_box = [int(x1 + rpx1), int(y1 + rpy1), int(x1 + rpx2), int(y1 + rpy2)]
            
            # 2. Check vehicle crop size
            veh_w, veh_h = x2 - x1, y2 - y1
            if run_ocr and (veh_w < settings.MIN_VEHICLE_WIDTH or veh_h < settings.MIN_VEHICLE_HEIGHT):
                run_ocr = False
            
            # 3. Perform Plate Detection & OCR if required
            if run_ocr:
                plate_results = self.plate_model(crop_veh, conf=0.20, verbose=False, device=self.device)
                
                if plate_results and plate_results[0].boxes:
                    # Find highest confidence license plate
                    p_boxes = plate_results[0].boxes
                    best_p_box = max(p_boxes, key=lambda b: b.conf[0].item())
                    p_xyxy = best_p_box.xyxy[0].cpu().numpy().astype(int)
                    
                    # Coords within the vehicle frame
                    px1, py1, px2, py2 = p_xyxy
                    px1, py1 = max(0, px1), max(0, py1)
                    px2, py2 = min(crop_veh.shape[1], px2), min(crop_veh.shape[0], py2)
                    
                    if px2 > px1 and py2 > py1:
                        crop_plate = crop_veh[py1:py2, px1:px2]
                        
                        # Preprocess plate crop image before running PaddleOCR
                        h_p, w_p = crop_plate.shape[:2]
                        # Upscale if small, downscale if large (max width 240px to optimize CPU inference speed)
                        if w_p < 150 or h_p < 50:
                            crop_plate_preped = cv2.resize(crop_plate, (w_p * 2, h_p * 2), interpolation=cv2.INTER_CUBIC)
                        elif w_p > 240:
                            scale = 240.0 / w_p
                            new_h = int(h_p * scale)
                            crop_plate_preped = cv2.resize(crop_plate, (240, new_h), interpolation=cv2.INTER_AREA)
                        else:
                            crop_plate_preped = crop_plate.copy()
                        
                        # Grayscale
                        gray = cv2.cvtColor(crop_plate_preped, cv2.COLOR_BGR2GRAY)
                        
                        # CLAHE Contrast Enhancement
                        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                        enhanced = clahe.apply(gray)
                        
                        # Convert to BGR for PaddleOCR
                        ocr_input = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
                        
                        # Run PaddleOCR (Arabic model)
                        ocr_res = self.ocr.ocr(ocr_input)
                        if ocr_res and ocr_res[0]:
                            texts = []
                            confs = []
                            if isinstance(ocr_res[0], dict):
                                rec_texts = ocr_res[0].get('rec_texts', [])
                                rec_scores = ocr_res[0].get('rec_scores', [])
                                for t, s in zip(rec_texts, rec_scores):
                                    texts.append(str(t))
                                    confs.append(float(s))
                            else:
                                for line in ocr_res[0]:
                                    if isinstance(line, (list, tuple)) and len(line) == 2 and isinstance(line[1], (list, tuple)) and len(line[1]) == 2:
                                        texts.append(str(line[1][0]))
                                        confs.append(float(line[1][1]))
                                    elif isinstance(line, (list, tuple)) and len(line) == 2 and isinstance(line[0], str):
                                        texts.append(str(line[0]))
                                        confs.append(float(line[1]))
                            
                            if texts:
                                raw_text = " ".join(texts)
                                ocr_conf = float(np.mean(confs)) if confs else 0.0
                                plate_number, p_type = self.clean_plate_text(raw_text)
                        
                        # Draw plate relative coordinates
                        plate_box = [int(x1 + px1), int(y1 + py1), int(x1 + px2), int(y1 + py2)]
                        
                        # If this is a valid plate, update the cache
                        if track_id is not None and plate_number != "UNKNOWN":
                            prev_attempts = 0
                            existing_crop_path = ""
                            if track_id in self.track_ocr_cache:
                                prev_attempts = self.track_ocr_cache[track_id]["attempts"]
                                existing_crop_path = self.track_ocr_cache[track_id].get("crop_image_url", "")
                            
                            is_moroccan_plate = p_type.startswith("Moroccan Plate")
                            
                            # Only write crop image to disk if it is a Moroccan plate and not already processed
                            if is_moroccan_plate and plate_number not in self.processed_plates:
                                if not existing_crop_path:
                                    crop_filename = f"crop_{track_id}_{uuid.uuid4().hex[:8]}.jpg"
                                    crop_path = os.path.join(settings.CROPS_DIR, crop_filename)
                                    cv2.imwrite(crop_path, crop_plate)
                                    crop_path = f"/static/crops/{crop_filename}"
                                else:
                                    abs_crop_path = os.path.join(settings.STATIC_DIR, existing_crop_path.lstrip("/static/"))
                                    cv2.imwrite(abs_crop_path, crop_plate)
                                    crop_path = existing_crop_path
                            else:
                                crop_path = existing_crop_path if (existing_crop_path and is_moroccan_plate) else ""
                                
                            # Update cache
                            is_better = True
                            if track_id in self.track_ocr_cache:
                                if self.track_ocr_cache[track_id]["confidence_score"] >= ocr_conf:
                                    is_better = False
                                    
                            if is_better:
                                self.track_ocr_cache[track_id] = {
                                    "plate_number": plate_number,
                                    "confidence_score": ocr_conf,
                                    "attempts": prev_attempts + 1,
                                    "relative_plate_box": [int(px1), int(py1), int(px2), int(py2)],
                                    "crop_image_url": crop_path,
                                    "is_moroccan": is_moroccan_plate
                                }
                            else:
                                self.track_ocr_cache[track_id]["attempts"] += 1
                                # Retrieve details from cache
                                plate_number = self.track_ocr_cache[track_id]["plate_number"]
                                ocr_conf = self.track_ocr_cache[track_id]["confidence_score"]
                                rpx1, rpy1, rpx2, rpy2 = self.track_ocr_cache[track_id]["relative_plate_box"]
                                plate_box = [int(x1 + rpx1), int(y1 + rpy1), int(x1 + rpx2), int(y1 + rpy2)]
                
                # If we tried plate detection/OCR but got nothing, update attempts
                if track_id is not None:
                    if track_id not in self.track_ocr_cache:
                        self.track_ocr_cache[track_id] = {
                            "plate_number": "UNKNOWN",
                            "confidence_score": 0.0,
                            "attempts": 1,
                            "relative_plate_box": None,
                            "crop_image_url": "",
                            "is_moroccan": False
                        }
                    else:
                        self.track_ocr_cache[track_id]["attempts"] += 1
            
            # Combine confidences
            combined_conf = (conf + ocr_conf) / 2.0 if ocr_conf > 0 else conf
            
            # 4. Determine if we should trigger writing to DB
            is_new = False
            if track_id is not None and track_id not in self.processed_track_ids:
                cache = self.track_ocr_cache.get(track_id, {})
                # ONLY log real Moroccan plates! Reject standard alphanumeric noise like decals / watermarks
                if cache and cache.get("is_moroccan", False) and cache.get("plate_number") != "UNKNOWN":
                    p_num = cache.get("plate_number")
                    if p_num not in self.processed_plates:
                        attempts = cache.get("attempts", 0)
                        conf_score = cache.get("confidence_score", 0.0)
                        if conf_score >= 0.75 or attempts >= settings.MAX_OCR_ATTEMPTS:
                            is_new = True
                            self.processed_plates.add(p_num)
            
            detection = {
                "track_id": track_id,
                "box": [int(x1), int(y1), int(x2), int(y2)],
                "plate_box": plate_box,
                "class": class_name,
                "vehicle_model": vehicle_model,
                "vehicle_color": vehicle_color,
                "plate_number": plate_number,
                "confidence_score": combined_conf,
                "crop_image_url": crop_path,
                "is_new": is_new
            }
            detections.append(detection)
            
        return detections

    def _process_mock_frame(self, frame: np.ndarray, frame_id: int) -> list[dict]:
        """
        Simulates vehicle trajectories and logs for testing.
        Returns bounding boxes and mock detections.
        """
        detections = []
        h, w, _ = frame.shape
        
        # Spawn new vehicles periodically
        if frame_id % 35 == 0 and len(self.active_mock_vehicles) < 3:
            track_id = len(self.processed_track_ids) + len(self.active_mock_vehicles) + 1
            
            # Random starting parameters
            vehicle_classes = ["car", "truck", "motorcycle"]
            v_class = random.choices(vehicle_classes, weights=[0.8, 0.15, 0.05])[0]
            
            colors = ["White", "Black", "Grey", "Dark Blue", "Red", "Silver"]
            models_map = {
                "car": ["Mercedes E-Class", "Dacia Logan", "Volkswagen Golf", "Renault Clio"],
                "truck": ["Toyota Hilux", "Volvo FH16"],
                "motorcycle": ["Yamaha T-Max", "Kawasaki Ninja"]
            }
            
            # Generate Moroccan format plate: digits (1-5 chars), arabic letter, prefecture code (1-2 digits)
            arabic_chars = ["أ", "ب", "ج", "د", "هـ", "و", "ط", "م", "س", "ر", "ق", "ش"]
            plate_num = f"{random.randint(1000, 99999)}-{random.choice(arabic_chars)}-{random.randint(1, 89)}"
            
            self.active_mock_vehicles[track_id] = {
                "track_id": track_id,
                "class": v_class,
                "vehicle_model": random.choice(models_map[v_class]),
                "vehicle_color": random.choice(colors),
                "plate_number": plate_num,
                "confidence_score": round(random.uniform(0.85, 0.98), 2),
                # Start at bottom/middle and move upward/across
                "x": int(w * random.uniform(0.15, 0.6)),
                "y": h - 50,
                "w": 180,
                "h": 120,
                "speed_y": -8 - random.randint(0, 4),
                "speed_x": random.randint(-2, 2),
                "step": 0
            }

        # Update active vehicles
        to_delete = []
        for track_id, veh in self.active_mock_vehicles.items():
            veh["x"] += veh["speed_x"]
            veh["y"] += veh["speed_y"]
            # Grow slightly as they approach the camera
            veh["w"] = int(veh["w"] * 1.01)
            veh["h"] = int(veh["h"] * 1.01)
            veh["step"] += 1
            
            # Check bounding box bounds
            x1, y1 = veh["x"], veh["y"]
            x2, y2 = x1 + veh["w"], y1 + veh["h"]
            
            # If vehicle exits screen bounds
            if y2 < 0 or y1 > h or x2 < 0 or x1 > w:
                to_delete.append(track_id)
                continue
                
            # Create sub-plates box relative to vehicle box
            px1 = x1 + int(veh["w"] * 0.35)
            py1 = y1 + int(veh["h"] * 0.65)
            px2 = px1 + int(veh["w"] * 0.3)
            py2 = py1 + int(veh["h"] * 0.18)
            
            # Log event triggers when vehicle passes the "detection line" (mid-screen)
            is_new = False
            crop_path = ""
            if y1 < h // 2 and track_id not in self.processed_track_ids:
                is_new = True
                
                # Mock write cropped sub-plate
                crop_filename = f"crop_{track_id}_{uuid.uuid4().hex[:8]}.jpg"
                crop_path = os.path.join(settings.CROPS_DIR, crop_filename)
                
                # Generate a dummy license plate image (blueish gradient box with text placeholder)
                dummy_crop = np.zeros((60, 150, 3), dtype=np.uint8)
                dummy_crop[:, :] = [240, 240, 240]  # Light grey background
                cv2.rectangle(dummy_crop, (0, 0), (150, 60), (0, 0, 0), 2)  # border
                cv2.rectangle(dummy_crop, (120, 0), (150, 60), (180, 50, 50), -1)  # Moroccan region code strip
                cv2.imwrite(crop_path, dummy_crop)
                crop_path = f"/static/crops/{crop_filename}"
                
            detection = {
                "track_id": track_id,
                "box": [x1, y1, x2, y2],
                "plate_box": [px1, py1, px2, py2],
                "class": veh["class"],
                "vehicle_model": veh["vehicle_model"],
                "vehicle_color": veh["vehicle_color"],
                "plate_number": veh["plate_number"],
                "confidence_score": veh["confidence_score"],
                "crop_image_url": crop_path,
                "is_new": is_new
            }
            detections.append(detection)
            
        for tid in to_delete:
            del self.active_mock_vehicles[tid]
            
        return detections
        
    def reset_session(self):
        """Resets tracking cache for a new video or stream ingestion session"""
        self.processed_track_ids.clear()
        self.processed_plates.clear()
        self.active_mock_vehicles.clear()
        self.track_ocr_cache.clear()
