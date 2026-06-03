from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from app.core.config import settings
from app.db.session import engine, Base
from app.api.endpoints import router as api_router

# Create DB tables automatically on startup for development simplicity
print("[INFO] Initializing PostgreSQL tables...")
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="High-Performance ANPR and Vehicle Intelligence SaaS with YOLO26 and PaddleOCR",
    version="1.0.0"
)

# Enable CORS for frontend workspace access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure upload/crop directory exists
os.makedirs(settings.CROPS_DIR, exist_ok=True)

# Mount static folder to serve cropped plates and uploaded media
app.mount("/static", StaticFiles(directory=settings.STATIC_DIR), name="static")

# Include central router
app.include_router(api_router, prefix="/api/v1")

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "project": settings.PROJECT_NAME,
        "mock_pipeline": settings.MOCK_VISION_PIPELINE
    }

if __name__ == "__main__":
    import uvicorn
    # Start on port 8000
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
