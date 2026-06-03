import os
import uuid
import json
import asyncio
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from sqlalchemy import func
import redis.asyncio as aioredis
import redis

from app.core.config import settings
from app.db.session import get_db
from app.db.models import VehicleLog
from app.workers.tasks import process_video_task

router = APIRouter()

# Connect to Redis (Sync for API commands, Async is instantiated inside WebSocket handler)
redis_client = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=0)

@router.post("/upload")
async def upload_media(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Accepts static image/video files for ANPR analysis.
    Videos are processed asynchronously via Celery;
    Images are processed synchronously or simulated.
    """
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in [".jpg", ".jpeg", ".png", ".mp4", ".avi", ".mov"]:
        raise HTTPException(status_code=400, detail="Unsupported media format.")

    session_id = str(uuid.uuid4())
    
    # Save the file locally
    filename = f"{session_id}{file_ext}"
    upload_path = os.path.join(settings.STATIC_DIR, filename)
    
    try:
        with open(upload_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    # For images, we can either trigger a brief tasks task or return results directly.
    # To keep the frontend flow consistent, we trigger a celery worker task for both,
    # letting the WebSocket stream back the parsed overlays and final result instantly!
    process_video_task.delay(upload_path, session_id)
    
    return {
        "session_id": session_id,
        "media_url": f"/static/{filename}",
        "type": "video" if file_ext in [".mp4", ".avi", ".mov"] else "image"
    }

@router.post("/stream/start")
async def start_stream(
    url: str = Form(...)
):
    """
    Initializes frame capture from an RTSP feed, HLS link, or Webcam stream.
    Returns session ID for opening WebSocket streaming listeners.
    """
    session_id = str(uuid.uuid4())
    
    # Resolve webcam ID to integer if requested
    source = url
    if url.lower() == "webcam":
        source = "webcam"
    
    # Trigger Celery async frame processing loop
    process_video_task.delay(source, session_id)
    
    return {
        "session_id": session_id,
        "status": "started",
        "source": source
    }

@router.post("/stream/stop/{session_id}")
async def stop_stream(session_id: str):
    """
    Sends a stop flag to Redis to interrupt the active processing loop.
    """
    redis_client.set(f"stop_{session_id}", "1", ex=30)
    return {"status": "stop_signal_sent", "session_id": session_id}

@router.get("/logs")
async def get_logs(
    search: str = None,
    color: str = None,
    vehicle_type: str = None,
    start_date: str = None,
    end_date: str = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """
    Fetches ANPR vehicle logging history with support for pagination and filters.
    """
    query = db.query(VehicleLog)
    
    if search:
        query = query.filter(VehicleLog.plate_number.ilike(f"%{search}%"))
    if color:
        query = query.filter(VehicleLog.vehicle_color.ilike(f"%{color}%"))
    if vehicle_type:
        query = query.filter(VehicleLog.vehicle_type.ilike(f"%{vehicle_type}%"))
        
    if start_date:
        try:
            sd = datetime.fromisoformat(start_date)
            query = query.filter(VehicleLog.timestamp >= sd)
        except ValueError:
            pass
            
    if end_date:
        try:
            ed = datetime.fromisoformat(end_date)
            query = query.filter(VehicleLog.timestamp <= ed)
        except ValueError:
            pass

    total = query.count()
    logs = query.order_by(VehicleLog.timestamp.desc()).limit(limit).offset(offset).all()
    
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "data": [log.to_dict() for log in logs]
    }

@router.get("/stats")
async def get_stats(db: Session = Depends(get_db)):
    """
    Aggregates metrics for dashboard charts.
    """
    # Total vehicles registered in the last 24 hours
    since_24h = datetime.utcnow() - timedelta(hours=24)
    total_today = db.query(VehicleLog).filter(VehicleLog.timestamp >= since_24h).count()
    
    # Distribution of types
    type_stats = db.query(
        VehicleLog.vehicle_type, func.count(VehicleLog.id)
    ).group_by(VehicleLog.vehicle_type).all()
    
    # Distribution of colors
    color_stats = db.query(
        VehicleLog.vehicle_color, func.count(VehicleLog.id)
    ).group_by(VehicleLog.vehicle_color).all()
    
    # Hourly traffic stats (aggregated by hour of day)
    hourly_query = db.query(
        func.extract('hour', VehicleLog.timestamp).label('hour'),
        func.count(VehicleLog.id).label('count')
    ).group_by(func.extract('hour', VehicleLog.timestamp)).all()
    
    # Format database response
    type_data = [{"name": t[0] or "Unknown", "value": t[1]} for t in type_stats]
    color_data = [{"name": c[0] or "Unknown", "value": c[1]} for c in color_stats]
    
    hourly_map = {int(h[0]): h[1] for h in hourly_query}
    # Ensure all 24 hours are represented
    hourly_data = [{"hour": f"{h:02d}:00", "count": hourly_map.get(h, 0)} for h in range(24)]

    # No fallback, return empty/actual values to avoid confusing the user
    pass

    return {
        "total_today": total_today,
        "vehicle_types": type_data,
        "vehicle_colors": color_data,
        "hourly_traffic": hourly_data
    }

@router.websocket("/ws/stream/{session_id}")
async def websocket_stream(websocket: WebSocket, session_id: str):
    """
    Subscribes asynchronously to the Redis Pub/Sub channel for the stream session,
    relaying overlay frames and detection events directly to the frontend.
    """
    await websocket.accept()
    print(f"[INFO] WebSocket connection established for session {session_id}")
    
    # Establish async Redis client connection
    r = aioredis.from_url(f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/0")
    pubsub = r.pubsub()
    await pubsub.subscribe(f"stream_{session_id}")
    
    try:
        while True:
            # Check for message with 1s timeout to ensure non-blocking loop
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message:
                data = message['data'].decode('utf-8')
                await websocket.send_text(data)
                
                # Check for termination events
                payload = json.loads(data)
                if payload.get("type") in ["complete", "error"]:
                    print(f"[INFO] Stream session {session_id} finished. Closing WebSocket.")
                    break
                    
            await asyncio.sleep(0.01)
    except WebSocketDisconnect:
        print(f"[INFO] Client disconnected WebSocket session {session_id}")
    except Exception as e:
        print(f"[ERROR] WebSocket failure: {str(e)}")
    finally:
        # Flag the celery task to stop just in case the client closed early
        await r.set(f"stop_{session_id}", "1", ex=30)
        await pubsub.unsubscribe(f"stream_{session_id}")
        await r.close()
        try:
            await websocket.close()
        except Exception:
            pass
