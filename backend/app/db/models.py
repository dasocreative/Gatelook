import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, DateTime
from sqlalchemy.dialects.postgresql import UUID
from app.db.session import Base

class VehicleLog(Base):
    __tablename__ = "vehicle_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    vehicle_type = Column(String(50), nullable=True, index=True)
    vehicle_model = Column(String(100), nullable=True)
    vehicle_color = Column(String(50), nullable=True, index=True)
    plate_number = Column(String(50), nullable=False, index=True)
    confidence_score = Column(Float, nullable=False)
    crop_image_url = Column(String(255), nullable=True)

    def to_dict(self):
        return {
            "id": str(self.id),
            "timestamp": self.timestamp.isoformat(),
            "vehicle_type": self.vehicle_type,
            "vehicle_model": self.vehicle_model,
            "vehicle_color": self.vehicle_color,
            "plate_number": self.plate_number,
            "confidence_score": round(self.confidence_score, 4),
            "crop_image_url": self.crop_image_url
        }
