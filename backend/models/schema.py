from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from database import Base

class Identity(Base):
    __tablename__ = "identities"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    reference_image_path = Column(String, nullable=True)
    reference_audio_path = Column(String, nullable=True)
    face_embedding = Column(JSON, nullable=True) # Stored as JSON list of floats
    voice_embedding = Column(JSON, nullable=True) # Stored as JSON list of floats
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    investigations = relationship("Investigation", back_populates="identity")

class Investigation(Base):
    __tablename__ = "investigations"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, index=True)
    file_path = Column(String)
    file_size_bytes = Column(Integer)
    sha256_hash = Column(String, index=True)
    media_type = Column(String)  # 'video', 'image', 'audio'
    status = Column(String, default="pending") # pending, analyzing, completed, failed
    
    # Optional reference identity
    identity_id = Column(Integer, ForeignKey("identities.id"), nullable=True)
    identity = relationship("Identity", back_populates="investigations")
    
    # Metadata
    duration_seconds = Column(Float, nullable=True)
    resolution = Column(String, nullable=True)
    fps = Column(Float, nullable=True)
    frames_extracted = Column(Integer, default=0)
    
    # Risk Fusion
    overall_risk_score = Column(Float, nullable=True) # 0.0 to 1.0
    risk_level = Column(String, nullable=True) # LOW, MEDIUM, HIGH, CRITICAL
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    evidence_items = relationship("Evidence", back_populates="investigation")
    analysis_results = relationship("AnalysisResult", back_populates="investigation")
    timeline_events = relationship("TimelineEvent", back_populates="investigation")

class Evidence(Base):
    __tablename__ = "evidence"
    
    id = Column(Integer, primary_key=True, index=True)
    investigation_id = Column(Integer, ForeignKey("investigations.id"))
    evidence_type = Column(String) # 'original', 'frame', 'audio_extract', 'thumbnail'
    file_path = Column(String)
    sha256_hash = Column(String, nullable=True)
    perceptual_hash = Column(String, nullable=True)
    timestamp_offset = Column(Float, nullable=True) # For video frames
    metadata_json = Column(JSON, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    investigation = relationship("Investigation", back_populates="evidence_items")

class AnalysisResult(Base):
    __tablename__ = "analysis_results"
    
    id = Column(Integer, primary_key=True, index=True)
    investigation_id = Column(Integer, ForeignKey("investigations.id"))
    module_name = Column(String) # 'deepfake', 'identity', 'voice', 'consistency', 'c2pa', 'similarity'
    score = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)
    result_data = Column(JSON, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    investigation = relationship("Investigation", back_populates="analysis_results")

class TimelineEvent(Base):
    __tablename__ = "timeline_events"
    
    id = Column(Integer, primary_key=True, index=True)
    investigation_id = Column(Integer, ForeignKey("investigations.id"))
    event_type = Column(String)
    description = Column(String)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    investigation = relationship("Investigation", back_populates="timeline_events")
