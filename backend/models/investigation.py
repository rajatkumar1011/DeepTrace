from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.sql import func
from database import Base

class Investigation(Base):
    __tablename__ = "investigations"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, index=True)
    file_path = Column(String)
    file_size_bytes = Column(Integer)
    sha256_hash = Column(String, index=True)
    media_type = Column(String)  # 'video', 'image', 'audio'
    
    # Metadata for video
    duration_seconds = Column(Float, nullable=True)
    resolution = Column(String, nullable=True)
    fps = Column(Float, nullable=True)
    frames_extracted = Column(Integer, default=0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
