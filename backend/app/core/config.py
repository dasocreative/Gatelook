import os
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    PROJECT_NAME: str = "ANPR & Vehicle Intelligence SaaS"
    ENV: str = Field(default="development", validation_alias="ENV")
    
    # Database Settings
    POSTGRES_USER: str = Field(default="postgres", validation_alias="POSTGRES_USER")
    POSTGRES_PASSWORD: str = Field(default="postgres", validation_alias="POSTGRES_PASSWORD")
    POSTGRES_HOST: str = Field(default="db", validation_alias="POSTGRES_HOST")
    POSTGRES_PORT: str = Field(default="5432", validation_alias="POSTGRES_PORT")
    POSTGRES_DB: str = Field(default="anpr_saas", validation_alias="POSTGRES_DB")

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    # Redis and Celery Settings
    REDIS_HOST: str = Field(default="redis", validation_alias="REDIS_HOST")
    REDIS_PORT: int = Field(default=6379, validation_alias="REDIS_PORT")

    @property
    def CELERY_BROKER_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    @property
    def CELERY_RESULT_BACKEND(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    # AI Pipeline Settings
    # Defaulting mock mode to true so it works out-of-the-box, but can be set to false for real inference
    MOCK_VISION_PIPELINE: bool = Field(default=True, validation_alias="MOCK_VISION_PIPELINE")
    
    YOLO_VEHICLE_MODEL: str = Field(default="yolov8n.pt", validation_alias="YOLO_VEHICLE_MODEL")
    YOLO_PLATE_MODEL: str = Field(default="yolov8n-plate.pt", validation_alias="YOLO_PLATE_MODEL")
    USE_GPU: bool = Field(default=False, validation_alias="USE_GPU")
    
    # Ingestion optimizations
    FRAME_SKIP: int = Field(default=3, validation_alias="FRAME_SKIP")  # process every Nth frame
    MOTION_THRESHOLD: float = Field(default=0.01, validation_alias="MOTION_THRESHOLD")
    MAX_OCR_ATTEMPTS: int = Field(default=5, validation_alias="MAX_OCR_ATTEMPTS")
    MIN_VEHICLE_WIDTH: int = Field(default=80, validation_alias="MIN_VEHICLE_WIDTH")
    MIN_VEHICLE_HEIGHT: int = Field(default=80, validation_alias="MIN_VEHICLE_HEIGHT")

    # Media storage paths
    STATIC_DIR: str = Field(default="./static", validation_alias="STATIC_DIR")
    CROPS_DIR: str = Field(default="./static/crops", validation_alias="CROPS_DIR")

    class Config:
        case_sensitive = True
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()

# Ensure folders exist
os.makedirs(settings.STATIC_DIR, exist_ok=True)
os.makedirs(settings.CROPS_DIR, exist_ok=True)
