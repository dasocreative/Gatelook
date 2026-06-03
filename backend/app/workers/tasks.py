import os
import json
import time
import base64
import cv2
import numpy as np
import redis
from app.workers.celery_app import celery_app
from app.core.pipeline import ANPRPipeline
from app.core.config import settings
from app.db.session import SessionLocal
from app.db.models import VehicleLog

# Connect to Redis
redis_client = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=0)

@celery_app.task(name="app.workers.tasks.process_video_task")
def process_video_task(video_source: str, session_id: str):
    """
    Asynchronous Celery task that reads a static video file or an RTSP stream,
    feeds frames into the YOLO+PaddleOCR pipeline, logs results to PostgreSQL,
    and publishes real-time frames/telemetry via Redis Pub/Sub.
    """
    print(f"[INFO] Starting ANPR session {session_id} for source: {video_source}")
    
    # Initialize the pipeline
    pipeline = ANPRPipeline()
    
    # Open capture source (video file path, RTSP url, or device ID)
    # Check if we should use mock webcam input (blank frame generator) if source is 'webcam'
    is_webcam = video_source.lower() == "webcam" or video_source == "0"
    
    if is_webcam and settings.MOCK_VISION_PIPELINE:
        cap = None
        w, h = 640, 480
    else:
        # Resolve path
        src = video_source
        if not is_webcam and not src.startswith("rtsp://") and not src.startswith("http://") and not src.startswith("https://"):
            if not os.path.exists(src):
                error_msg = f"Video source file not found: {src}"
                print(f"[ERROR] {error_msg}")
                redis_client.publish(f"stream_{session_id}", json.dumps({"type": "error", "message": error_msg}))
                return False
        
        cap = cv2.VideoCapture(src)
        if not cap.isOpened():
            error_msg = f"Failed to open video source: {src}"
            print(f"[ERROR] {error_msg}")
            redis_client.publish(f"stream_{session_id}", json.dumps({"type": "error", "message": error_msg}))
            return False
            
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
    frame_id = 0
    db = SessionLocal()
    
    # Keep track of frame times for FPS calculation
    last_time = time.time()
    
    try:
        while True:
            # Check if frontend requested to stop the stream
            stop_signal = redis_client.get(f"stop_{session_id}")
            if stop_signal:
                print(f"[INFO] Received stop signal for session {session_id}")
                redis_client.publish(f"stream_{session_id}", json.dumps({"type": "status", "message": "Stream stopped by user"}))
                break

            if is_webcam and settings.MOCK_VISION_PIPELINE:
                # Generate a mock background canvas representing a highway lane
                frame = np.zeros((h, w, 3), dtype=np.uint8)
                frame[:, :] = [45, 45, 45]  # Dark background
                # Draw lanes
                cv2.line(frame, (w // 2, 0), (w // 2, h), (255, 255, 255), 2)
                cv2.line(frame, (100, 0), (50, h), (180, 180, 180), 3)
                cv2.line(frame, (w - 100, 0), (w - 50, h), (180, 180, 180), 3)
                ret = True
            else:
                ret, frame = cap.read()
                if not ret:
                    # Video completed
                    print(f"[INFO] Video stream ended for session {session_id}")
                    break

            frame_id += 1
            
            # Apply frame skip for performance (except in mock mode webcam loop)
            if not (is_webcam and settings.MOCK_VISION_PIPELINE):
                if frame_id % settings.FRAME_SKIP != 0:
                    continue

            # Run frame through vision pipeline
            detections = pipeline.process_frame(frame, frame_id)
            
            # Draw detections on frame
            for det in detections:
                box = det["box"]
                p_box = det["plate_box"]
                track_id = det["track_id"]
                
                # Draw bounding box for vehicle
                cv2.rectangle(frame, (box[0], box[1]), (box[2], box[3]), (59, 130, 246), 2)  # Sleek blue
                label = f"ID:{track_id} {det['class']} ({det['vehicle_color']})"
                cv2.putText(frame, label, (box[0], box[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 2)
                
                # Draw plate bounding box
                if p_box:
                    cv2.rectangle(frame, (p_box[0], p_box[1]), (p_box[2], p_box[3]), (239, 68, 68), 2)  # High contrast red
                    cv2.putText(frame, det["plate_number"], (p_box[0], p_box[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (239, 68, 68), 2)
                
                # Save and publish log if new vehicle logged
                if det["is_new"]:
                    new_log = VehicleLog(
                        vehicle_type=det["class"].capitalize(),
                        vehicle_model=det["vehicle_model"],
                        vehicle_color=det["vehicle_color"],
                        plate_number=det["plate_number"],
                        confidence_score=det["confidence_score"],
                        crop_image_url=det["crop_image_url"]
                    )
                    db.add(new_log)
                    db.commit()
                    db.refresh(new_log)
                    
                    # Update processed ids
                    pipeline.processed_track_ids.add(track_id)
                    
                    # Broadcast event log
                    event_data = {
                        "type": "new_detection",
                        "data": new_log.to_dict()
                    }
                    redis_client.publish(f"stream_{session_id}", json.dumps(event_data))

            # Calculate actual FPS
            curr_time = time.time()
            fps = 1.0 / (curr_time - last_time) if (curr_time - last_time) > 0 else 0
            last_time = curr_time
            
            # Print status details overlay
            status_text = f"FPS: {fps:.1f} | Frame: {frame_id} | Active Tracks: {len(pipeline.active_mock_vehicles) if settings.MOCK_VISION_PIPELINE else 'Active'}"
            cv2.rectangle(frame, (10, 10), (320, 40), (0, 0, 0), -1)
            cv2.putText(frame, status_text, (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 240, 0), 1)

            # Resize processed frame and encode to base64
            # Compress to JPG to keep bandwidth consumption minimal
            resized = cv2.resize(frame, (640, 360))
            _, buffer = cv2.imencode('.jpg', resized, [cv2.IMWRITE_JPEG_QUALITY, 60])
            frame_b64 = base64.b64encode(buffer).decode('utf-8')
            
            frame_data = {
                "type": "frame",
                "image": f"data:image/jpeg;base64,{frame_b64}"
            }
            redis_client.publish(f"stream_{session_id}", json.dumps(frame_data))
            
            # Sleep slightly in mock webcam mode to replicate a camera FPS feed
            if is_webcam and settings.MOCK_VISION_PIPELINE:
                time.sleep(0.04)
            elif settings.MOCK_VISION_PIPELINE:
                # Video file mock playback control
                time.sleep(0.03)

        # Notify completion
        redis_client.publish(f"stream_{session_id}", json.dumps({"type": "complete"}))
        
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"[ERROR] Exception in video worker task:\n{tb}")
        redis_client.publish(f"stream_{session_id}", json.dumps({"type": "error", "message": str(e)}))
    finally:
        if cap is not None:
            cap.release()
        db.close()
        # Clean up stop signal
        redis_client.delete(f"stop_{session_id}")
        
    return True
