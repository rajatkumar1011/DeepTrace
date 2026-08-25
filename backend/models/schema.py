from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from database import Base

CONSENT_TEXT_VERSION = "1.0"
CONSENT_TEXT = (
    "I confirm that I am the person shown in the reference material, or that I am "
    "authorised to submit it on their behalf, and I consent to DeepTrace storing "
    "the reference image/audio and derived biometric templates locally for the "
    "purpose of comparing them against media I submit for investigation."
)


class Identity(Base):
    """A consent-based protected identity profile."""

    __tablename__ = "identities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    reference_image_path = Column(String, nullable=True)
    reference_audio_path = Column(String, nullable=True)
    face_embedding = Column(JSON, nullable=True)
    voice_embedding = Column(JSON, nullable=True)
    face_model = Column(String, nullable=True)
    voice_model = Column(String, nullable=True)
    consent_given = Column(Boolean, default=False)
    consent_text_version = Column(String, nullable=True)
    consent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    investigations = relationship("Investigation", back_populates="identity")


class Investigation(Base):
    """One case: a single piece of suspicious media plus everything derived from it."""

    __tablename__ = "investigations"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, index=True)
    file_path = Column(String)
    file_size_bytes = Column(Integer)
    sha256_hash = Column(String, index=True)
    perceptual_hash = Column(String, nullable=True)
    media_type = Column(String)
    status = Column(String, default="pending")
    progress_stage = Column(String, nullable=True)
    progress_percent = Column(Integer, default=0)
    error_message = Column(String, nullable=True)

    identity_id = Column(Integer, ForeignKey("identities.id"), nullable=True)
    identity = relationship("Identity", back_populates="investigations")

    duration_seconds = Column(Float, nullable=True)
    resolution = Column(String, nullable=True)
    fps = Column(Float, nullable=True)
    frames_extracted = Column(Integer, default=0)
    has_audio_stream = Column(Boolean, nullable=True)
    media_metadata = Column(JSON, nullable=True)
    source_urls = Column(JSON, nullable=True)

    overall_risk_score = Column(Float, nullable=True)
    risk_level = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    analysis_started_at = Column(DateTime(timezone=True), nullable=True)
    analysis_completed_at = Column(DateTime(timezone=True), nullable=True)

    evidence_items = relationship("Evidence", back_populates="investigation", cascade="all, delete-orphan")
    analysis_results = relationship("AnalysisResult", back_populates="investigation", cascade="all, delete-orphan")
    timeline_events = relationship("TimelineEvent", back_populates="investigation", cascade="all, delete-orphan")
    trace_sources = relationship("TraceSource", back_populates="investigation", cascade="all, delete-orphan")


class Evidence(Base):
    """A preserved artifact. ``original`` rows are never overwritten or replaced."""

    __tablename__ = "evidence"

    id = Column(Integer, primary_key=True, index=True)
    investigation_id = Column(Integer, ForeignKey("investigations.id"))
    evidence_type = Column(String)
    file_path = Column(String)
    sha256_hash = Column(String, nullable=True)
    perceptual_hash = Column(String, nullable=True)
    timestamp_offset = Column(Float, nullable=True)
    metadata_json = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    investigation = relationship("Investigation", back_populates="evidence_items")


class AnalysisResult(Base):
    """One module's output. Derived data — safe to discard and recompute."""

    __tablename__ = "analysis_results"

    id = Column(Integer, primary_key=True, index=True)
    investigation_id = Column(Integer, ForeignKey("investigations.id"))
    module_name = Column(String, index=True)
    score = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)
    status = Column(String, nullable=True)
    result_data = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    investigation = relationship("Investigation", back_populates="analysis_results")


class TraceSource(Base):
    """A public URL or locally supplied copy attached to an investigation."""

    __tablename__ = "trace_sources"

    id = Column(Integer, primary_key=True, index=True)
    investigation_id = Column(Integer, ForeignKey("investigations.id"))
    source_url = Column(String, nullable=True)
    title = Column(String, nullable=True)
    description = Column(String, nullable=True)
    origin = Column(String)  # "public_url" | "local_copy" | "url_reference_only"
    retrieval_status = Column(String)  # "fetched" | "rejected" | "failed" | "not_retrieved"
    retrieval_error = Column(String, nullable=True)
    file_path = Column(String, nullable=True)
    content_type = Column(String, nullable=True)
    bytes_downloaded = Column(Integer, nullable=True)
    sha256_hash = Column(String, nullable=True)
    perceptual_hash = Column(String, nullable=True)
    similarity = Column(Float, nullable=True)
    match_type = Column(String, nullable=True)
    similarity_label = Column(String, nullable=True)
    details = Column(JSON, nullable=True)
    discovered_at = Column(DateTime(timezone=True), server_default=func.now())

    investigation = relationship("Investigation", back_populates="trace_sources")


class TimelineEvent(Base):
    """Append-only case chronology."""

    __tablename__ = "timeline_events"

    id = Column(Integer, primary_key=True, index=True)
    investigation_id = Column(Integer, ForeignKey("investigations.id"))
    event_type = Column(String)
    description = Column(String)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    investigation = relationship("Investigation", back_populates="timeline_events")
