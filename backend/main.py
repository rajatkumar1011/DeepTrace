"""DeepTrace API.

Pipeline order, which is also the order the case timeline records:

    intake → metadata → frames → audio → manipulation → localization
           → identity → voice → A/V consistency → provenance
           → local copy tracing → risk fusion → preservation

Every module writes an ``AnalysisResult`` with an explicit ``status``. A module
that cannot run records *why* it could not; nothing is defaulted to a neutral
score, and no result is ever synthesised.
"""

import json
import os
import re
from datetime import datetime, timezone

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from database import Base, engine, get_db, migrate_sqlite
from models.schema import (
    CONSENT_TEXT,
    CONSENT_TEXT_VERSION,
    AnalysisResult,
    Evidence,
    Identity,
    Investigation,
    TimelineEvent,
    TraceSource,
)
from paths import (
    AUDIO_DIR,
    BENCHMARK_DIR,
    DEMO_DIR,
    EVIDENCE_DIR,
    FRAMES_DIR,
    IDENTITY_DIR,
    LOCALIZATION_DIR,
    PROJECT_ROOT,
    SOURCES_DIR,
    UPLOAD_DIR,
    ensure_runtime_dirs,
    repo_relative,
    report_path,
    resolve_inside,
    to_public_path,
    to_static_url,
)
from services.forensics import (
    calculate_perceptual_hash,
    calculate_sha256,
    collect_media_metadata,
    extract_sampled_frames,
    ffmpeg_available,
    probe_media,
    stream_to_disk,
    summarize_probe,
)

# ─── Configuration ───────────────────────────────────────────────────────────

def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, "").strip() or default))
    except ValueError:
        return default


MAX_UPLOAD_MB = _int_env("DEEPTRACE_MAX_UPLOAD_MB", 200)
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
MAX_REFERENCE_MB = _int_env("DEEPTRACE_MAX_REFERENCE_MB", 25)
MAX_REFERENCE_BYTES = MAX_REFERENCE_MB * 1024 * 1024
FRAME_SAMPLES = _int_env("DEEPTRACE_FRAME_SAMPLES", 12)

MEDIA_TYPES = {
    ".mp4": "video", ".avi": "video", ".mov": "video", ".mkv": "video", ".webm": "video",
    ".jpg": "image", ".jpeg": "image", ".png": "image", ".bmp": "image", ".webp": "image",
    ".wav": "audio", ".mp3": "audio", ".flac": "audio", ".ogg": "audio", ".m4a": "audio",
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}

# Derived artifacts are regenerated on every re-analysis; the original and any
# retrieved external copy are preserved permanently and never rewritten.
DERIVED_EVIDENCE_TYPES = ("frame", "localization", "audio")

DEFAULT_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]
CORS_ORIGINS = [
    origin.strip()
    for origin in (os.environ.get("DEEPTRACE_CORS_ORIGINS") or ",".join(DEFAULT_ORIGINS)).split(",")
    if origin.strip()
]

Base.metadata.create_all(bind=engine)
migrate_sqlite()
ensure_runtime_dirs()

app = FastAPI(
    title="DeepTrace API",
    version="1.0.0",
    description=(
        "Intelligent Digital Impersonation Detection and Forensic Evidence Preservation. "
        "Outputs are forensic indicators for investigator review, not proof."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.mount("/evidence", StaticFiles(directory=EVIDENCE_DIR), name="evidence")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
# Only the demo inputs are served statically. Generated reports and benchmark
# output live elsewhere under data/ and are reachable through API endpoints only.
if os.path.isdir(DEMO_DIR):
    app.mount("/demo-assets", StaticFiles(directory=DEMO_DIR), name="demo-assets")


# ─── Helpers ─────────────────────────────────────────────────────────────────

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(raw: str | None, fallback: str = "upload") -> str:
    """Reduce a client-supplied filename to a safe, path-traversal-free basename."""
    candidate = os.path.basename((raw or "").replace("\\", "/")).strip()
    candidate = _UNSAFE_CHARS.sub("_", candidate).strip("._-")
    if not candidate:
        return fallback
    stem, extension = os.path.splitext(candidate)
    return (stem[:100] or fallback) + extension[:12].lower()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def store_upload(upload: UploadFile, directory: str, max_bytes: int, max_mb: int) -> tuple[str, int, str]:
    """Persist an upload with a unique name, hashing the bytes as they are written."""
    from uuid import uuid4

    filename = safe_filename(upload.filename)
    destination = os.path.join(directory, f"{uuid4().hex}_{filename}")
    outcome = stream_to_disk(upload.file, destination, max_bytes)
    if outcome is None:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {max_mb} MB limit for this instance.",
        )
    size, digest = outcome
    if size == 0:
        try:
            os.remove(destination)
        except OSError:
            pass
        raise HTTPException(status_code=422, detail="The uploaded file is empty.")
    return destination, size, digest


def add_timeline(db: Session, investigation_id: int, event_type: str, description: str) -> None:
    db.add(TimelineEvent(
        investigation_id=investigation_id,
        event_type=event_type,
        description=description,
    ))
    db.commit()


def scrub_paths(value):
    """Recursively rewrite absolute artifact paths into repository-relative ones.

    Analysis services work with absolute paths internally, but a module payload
    is returned verbatim by the API and embedded in the report. Leaking
    ``C:\\Users\\...`` would expose the operator's directory layout, so every
    payload is scrubbed once here, at the point it becomes persistent.
    """
    if isinstance(value, dict):
        return {key: scrub_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [scrub_paths(item) for item in value]
    if isinstance(value, str) and len(value) > len(PROJECT_ROOT):
        normalised = value.replace("/", os.sep)
        if normalised.startswith(PROJECT_ROOT + os.sep):
            return to_public_path(normalised) or repo_relative(normalised) or os.path.basename(normalised)
    return value


def record_result(db: Session, investigation_id: int, module: str, payload: dict,
                  score: float | None = None, confidence: float | None = None,
                  status: str | None = None) -> None:
    """Write one module's output. One row per module per analysis run."""
    db.add(AnalysisResult(
        investigation_id=investigation_id,
        module_name=module,
        score=score,
        confidence=confidence,
        status=status or payload.get("status") or "completed",
        result_data=scrub_paths(payload),
    ))
    db.commit()


def set_progress(db: Session, inv: Investigation, stage: str, percent: int) -> None:
    inv.progress_stage = stage
    inv.progress_percent = max(0, min(100, percent))
    db.commit()


def evidence_payload(item: Evidence) -> dict:
    return {
        "id": item.id,
        "type": item.evidence_type,
        "file_path": to_public_path(item.file_path),
        "url": to_static_url(item.file_path),
        "filename": os.path.basename(item.file_path or ""),
        "sha256": item.sha256_hash,
        "perceptual_hash": item.perceptual_hash,
        "timestamp_offset": item.timestamp_offset,
        "metadata": item.metadata_json,
        "created_at": str(item.created_at) if item.created_at else None,
    }


def trace_payload(source: TraceSource) -> dict:
    return {
        "id": source.id,
        "source_url": source.source_url,
        "title": source.title,
        "description": source.description,
        "origin": source.origin,
        "retrieval_status": source.retrieval_status,
        "retrieval_error": source.retrieval_error,
        "file_path": to_public_path(source.file_path),
        "url": to_static_url(source.file_path),
        "content_type": source.content_type,
        "bytes_downloaded": source.bytes_downloaded,
        "sha256": source.sha256_hash,
        "perceptual_hash": source.perceptual_hash,
        "similarity": source.similarity,
        "match_type": source.match_type,
        "similarity_label": source.similarity_label,
        "details": source.details,
        "discovered_at": str(source.discovered_at) if source.discovered_at else None,
    }


def module_results(inv: Investigation) -> dict:
    """Latest row per module, so a re-run never leaves two rows racing to win."""
    latest: dict[str, AnalysisResult] = {}
    for result in sorted(inv.analysis_results, key=lambda r: (r.created_at or utc_now(), r.id)):
        latest[result.module_name] = result
    return {
        name: {
            "score": result.score,
            "confidence": result.confidence,
            "status": result.status,
            "data": result.result_data,
            "created_at": str(result.created_at) if result.created_at else None,
        }
        for name, result in latest.items()
    }


def module_data(inv: Investigation, module: str) -> dict | None:
    payload = module_results(inv).get(module)
    return (payload or {}).get("data")


def get_investigation_or_404(db: Session, investigation_id: int) -> Investigation:
    inv = db.query(Investigation).filter(Investigation.id == investigation_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return inv


# ─── Health & root ───────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    """Cheap readiness probe. Heavy models load lazily on the first analysis."""
    weights = os.path.join(os.path.dirname(__file__), "pretrained_models", "deepfakebench",
                           "xception_best.pth")
    speaker_dir = os.path.join(os.path.dirname(__file__), "pretrained_models",
                               "spkrec-ecapa-voxceleb")
    try:
        import c2pa  # noqa: F401
        c2pa_available = True
    except Exception:
        c2pa_available = False

    return {
        "status": "ok",
        "service": "DeepTrace",
        "version": "1.0.0",
        "capabilities": {
            "ffmpeg": ffmpeg_available(),
            "deepfakebench_xception_weights": os.path.isfile(weights),
            "speaker_model_cached": os.path.isdir(speaker_dir),
            "c2pa_reader": c2pa_available,
        },
        "limits": {
            "max_upload_mb": MAX_UPLOAD_MB,
            "max_reference_mb": MAX_REFERENCE_MB,
            "frame_samples": FRAME_SAMPLES,
        },
        "note": "Detection models are loaded on first use; capability flags report installed assets only.",
    }


@app.get("/")
def read_root():
    return {"status": "DeepTrace Backend Running", "docs": "/docs"}


# ─── Identity enrollment ─────────────────────────────────────────────────────

@app.get("/api/consent-text")
def consent_text():
    return {"version": CONSENT_TEXT_VERSION, "text": CONSENT_TEXT}


@app.post("/api/identity/enroll")
async def enroll_identity(
    name: str = Form(...),
    consent_given: str = Form("false"),
    reference_image: UploadFile = File(...),
    reference_audio: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    """Enroll a protected identity. Consent is required and recorded with a version."""
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Identity name is required.")
    if len(name) > 120:
        raise HTTPException(status_code=422, detail="Identity name must be 120 characters or fewer.")
    if str(consent_given).strip().lower() not in {"true", "1", "yes", "on"}:
        raise HTTPException(
            status_code=422,
            detail="Consent is required to enroll a protected identity and store biometric templates.",
        )
    if not reference_image or not reference_image.filename:
        raise HTTPException(status_code=422, detail="A reference image is required.")
    if os.path.splitext(safe_filename(reference_image.filename))[1].lower() not in IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="The reference image must be a JPEG, PNG, BMP or WebP file.",
        )

    image_path, _, _ = store_upload(reference_image, IDENTITY_DIR, MAX_REFERENCE_BYTES, MAX_REFERENCE_MB)

    face_embedding = None
    try:
        from services.identity import generate_face_embedding

        face_embedding = generate_face_embedding(image_path)
    except Exception as error:
        print(f"Face embedding error: {error}")

    if face_embedding is None:
        _remove_quietly(image_path)
        raise HTTPException(
            status_code=400,
            detail="No face was detected in the reference image. Upload a clear frontal face photo.",
        )

    audio_path = None
    voice_embedding = None
    voice_model = None
    if reference_audio and reference_audio.filename:
        if os.path.splitext(safe_filename(reference_audio.filename))[1].lower() not in AUDIO_EXTENSIONS:
            _remove_quietly(image_path)
            raise HTTPException(
                status_code=415,
                detail="The reference voice sample must be a WAV, MP3, FLAC, OGG or M4A file.",
            )
        audio_path, _, _ = store_upload(reference_audio, IDENTITY_DIR, MAX_REFERENCE_BYTES,
                                        MAX_REFERENCE_MB)
        try:
            from services.voice import embedding_model_name, generate_voice_embedding

            voice_embedding = generate_voice_embedding(audio_path)
            voice_model = embedding_model_name() if voice_embedding else None
        except Exception as error:
            print(f"Voice embedding error: {error}")

    identity = Identity(
        name=name,
        reference_image_path=image_path,
        reference_audio_path=audio_path,
        face_embedding=face_embedding,
        voice_embedding=voice_embedding,
        face_model="FaceNet InceptionResnetV1 (VGGFace2)" if len(face_embedding) == 512
                   else "Lightweight fallback embedding",
        voice_model=voice_model,
        consent_given=True,
        consent_text_version=CONSENT_TEXT_VERSION,
        consent_at=utc_now(),
    )
    try:
        db.add(identity)
        db.commit()
        db.refresh(identity)
    except Exception as error:
        db.rollback()
        _remove_quietly(image_path)
        _remove_quietly(audio_path)
        raise HTTPException(
            status_code=500, detail="Could not save the identity profile. Please try again.",
        ) from error

    return identity_payload(identity)


def identity_payload(identity: Identity) -> dict:
    return {
        "id": identity.id,
        "name": identity.name,
        "face_enrolled": identity.face_embedding is not None,
        "voice_enrolled": identity.voice_embedding is not None,
        "face_model": identity.face_model,
        "voice_model": identity.voice_model,
        "face_embedding_dimensions": len(identity.face_embedding) if identity.face_embedding else None,
        "consent_given": bool(identity.consent_given),
        "consent_text_version": identity.consent_text_version,
        "consent_at": str(identity.consent_at) if identity.consent_at else None,
        "created_at": str(identity.created_at) if identity.created_at else None,
        "reference_image_path": to_public_path(identity.reference_image_path),
        "reference_image_url": to_static_url(identity.reference_image_path),
        "has_reference_audio": bool(identity.reference_audio_path),
    }


@app.get("/api/identities")
def list_identities(db: Session = Depends(get_db)):
    identities = db.query(Identity).order_by(Identity.created_at.desc()).all()
    return [identity_payload(identity) for identity in identities]


@app.get("/api/identity/{identity_id}")
def get_identity(identity_id: int, db: Session = Depends(get_db)):
    identity = db.query(Identity).filter(Identity.id == identity_id).first()
    if not identity:
        raise HTTPException(status_code=404, detail="Identity not found")
    return identity_payload(identity)


# ─── Investigation intake ────────────────────────────────────────────────────

@app.post("/api/investigate")
async def create_investigation(
    file: UploadFile = File(...),
    identity_id: int = Form(None),
    source_urls: str = Form(None),
    db: Session = Depends(get_db),
):
    """Upload suspicious media, preserve it, and open a case."""
    if not file or not file.filename:
        raise HTTPException(status_code=422, detail="A media file is required.")

    filename = safe_filename(file.filename)
    extension = os.path.splitext(filename)[1].lower()
    media_type = MEDIA_TYPES.get(extension)
    if media_type is None:
        raise HTTPException(
            status_code=415,
            detail="Unsupported media type. Upload an image, video or audio file "
                   f"({', '.join(sorted(MEDIA_TYPES))}).",
        )
    if identity_id is not None and not db.query(Identity.id).filter(Identity.id == identity_id).first():
        raise HTTPException(status_code=422, detail="The selected protected identity no longer exists.")

    from services.tracing import parse_source_urls

    urls = parse_source_urls(source_urls)

    file_path, file_size, sha256_hash = store_upload(file, UPLOAD_DIR, MAX_UPLOAD_BYTES, MAX_UPLOAD_MB)
    perceptual_hash = calculate_perceptual_hash(file_path) if media_type == "image" else None

    investigation = Investigation(
        filename=filename,
        file_path=file_path,
        file_size_bytes=file_size,
        sha256_hash=sha256_hash,
        perceptual_hash=perceptual_hash,
        media_type=media_type,
        identity_id=identity_id,
        status="pending",
        progress_stage="Awaiting analysis",
        progress_percent=0,
        source_urls=urls or None,
    )

    probe = summarize_probe(probe_media(file_path))
    if probe:
        investigation.duration_seconds = probe.get("duration_seconds")
        investigation.resolution = probe.get("resolution")
        investigation.fps = probe.get("frame_rate")
        investigation.has_audio_stream = probe.get("has_audio")

    db.add(investigation)
    db.commit()
    db.refresh(investigation)

    db.add(Evidence(
        investigation_id=investigation.id,
        evidence_type="original",
        file_path=file_path,
        sha256_hash=sha256_hash,
        perceptual_hash=perceptual_hash,
        metadata_json={
            "original_filename": file.filename,
            "stored_filename": os.path.basename(file_path),
            "file_size_bytes": file_size,
            "preserved_at": utc_now().isoformat(timespec="seconds"),
            "note": "The original submission is preserved unmodified for the life of the case.",
        },
    ))
    db.commit()

    add_timeline(db, investigation.id, "investigation_created",
                 f"Investigation opened for {filename} ({media_type}).")
    add_timeline(db, investigation.id, "evidence_uploaded",
                 f"Original media preserved: {filename}, {file_size} bytes.")
    add_timeline(db, investigation.id, "hash_generated",
                 f"SHA-256 computed server-side during write: {sha256_hash}")
    if identity_id:
        identity = db.query(Identity).filter(Identity.id == identity_id).first()
        if identity:
            add_timeline(db, investigation.id, "identity_attached",
                         f"Case linked to protected identity: {identity.name}.")

    for url in urls:
        db.add(TraceSource(
            investigation_id=investigation.id,
            source_url=url,
            origin="url_reference_only",
            retrieval_status="not_retrieved",
            details={"note": "Recorded at intake. Run tracing to retrieve and compare a copy."},
        ))
    if urls:
        db.commit()
        add_timeline(db, investigation.id, "source_recorded",
                     f"{len(urls)} source URL(s) recorded at intake.")

    return {
        "message": "Investigation created successfully",
        "id": investigation.id,
        "status": investigation.status,
        "media_type": media_type,
        "sha256": sha256_hash,
        "source_urls": urls,
    }


@app.get("/api/investigations")
def list_investigations(db: Session = Depends(get_db)):
    investigations = db.query(Investigation).order_by(Investigation.created_at.desc()).all()
    return [
        {
            "id": inv.id,
            "filename": inv.filename,
            "media_type": inv.media_type,
            "status": inv.status,
            "progress_stage": inv.progress_stage,
            "progress_percent": inv.progress_percent,
            "risk_level": inv.risk_level,
            "overall_risk_score": inv.overall_risk_score,
            "created_at": str(inv.created_at) if inv.created_at else None,
            "identity_id": inv.identity_id,
            "identity_name": inv.identity.name if inv.identity else None,
        }
        for inv in investigations
    ]


@app.get("/api/investigation/{investigation_id}")
def get_investigation(investigation_id: int, db: Session = Depends(get_db)):
    inv = get_investigation_or_404(db, investigation_id)
    return {
        "id": inv.id,
        "filename": inv.filename,
        "file_path": to_public_path(inv.file_path),
        "media_url": to_static_url(inv.file_path),
        "file_size_bytes": inv.file_size_bytes,
        "sha256_hash": inv.sha256_hash,
        "perceptual_hash": inv.perceptual_hash,
        "media_type": inv.media_type,
        "status": inv.status,
        "progress_stage": inv.progress_stage,
        "progress_percent": inv.progress_percent,
        "error_message": inv.error_message,
        "identity_id": inv.identity_id,
        "identity_name": inv.identity.name if inv.identity else None,
        "duration_seconds": inv.duration_seconds,
        "resolution": inv.resolution,
        "fps": inv.fps,
        "frames_extracted": inv.frames_extracted,
        "has_audio_stream": inv.has_audio_stream,
        "media_metadata": inv.media_metadata,
        "source_urls": inv.source_urls or [],
        "overall_risk_score": inv.overall_risk_score,
        "risk_level": inv.risk_level,
        "created_at": str(inv.created_at) if inv.created_at else None,
        "analysis_started_at": str(inv.analysis_started_at) if inv.analysis_started_at else None,
        "analysis_completed_at": str(inv.analysis_completed_at) if inv.analysis_completed_at else None,
        "analysis_results": module_results(inv),
        "evidence": [evidence_payload(item) for item in
                     sorted(inv.evidence_items, key=lambda e: (e.evidence_type or "", e.id))],
        "trace_sources": [trace_payload(source) for source in inv.trace_sources],
        "report_available": os.path.isfile(report_path(inv.id)),
    }


# ─── Analysis pipeline ───────────────────────────────────────────────────────

@app.post("/api/investigation/{investigation_id}/analyze")
async def analyze_investigation(investigation_id: int, background_tasks: BackgroundTasks,
                                db: Session = Depends(get_db)):
    inv = get_investigation_or_404(db, investigation_id)
    if inv.status == "analyzing":
        raise HTTPException(status_code=409, detail="Analysis is already running for this investigation.")
    if not os.path.isfile(inv.file_path or ""):
        raise HTTPException(
            status_code=410,
            detail="The preserved media file is missing from the evidence store; it cannot be analysed.",
        )

    inv.status = "analyzing"
    inv.error_message = None
    inv.progress_stage = "Queued"
    inv.progress_percent = 0
    db.commit()

    background_tasks.add_task(run_analysis, investigation_id)
    return {"message": "Analysis started", "id": investigation_id, "status": "analyzing"}


def _remove_quietly(path: str | None) -> None:
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def reset_derived_state(db: Session, inv: Investigation) -> int:
    """Clear the previous run's derived output so re-analysis is idempotent.

    Module results and derived artifacts (frames, overlays, extracted audio) are
    recomputed from the original every run. The original submission and any
    retrieved external copy are never touched.
    """
    db.query(AnalysisResult).filter(AnalysisResult.investigation_id == inv.id).delete(
        synchronize_session=False)

    stale = db.query(Evidence).filter(
        Evidence.investigation_id == inv.id,
        Evidence.evidence_type.in_(DERIVED_EVIDENCE_TYPES),
    ).all()
    for item in stale:
        # Only ever unlink paths that resolve inside the evidence store.
        if item.file_path and resolve_inside(EVIDENCE_DIR, os.path.relpath(
                os.path.abspath(item.file_path), EVIDENCE_DIR)):
            _remove_quietly(item.file_path)
        db.delete(item)

    inv.frames_extracted = 0
    inv.overall_risk_score = None
    inv.risk_level = None
    db.commit()
    return len(stale)


def run_analysis(investigation_id: int) -> None:
    """Execute the full pipeline. Each stage is independently fault-isolated."""
    from database import SessionLocal

    db = SessionLocal()
    try:
        inv = db.query(Investigation).filter(Investigation.id == investigation_id).first()
        if not inv:
            return

        is_rerun = bool(inv.analysis_completed_at) or bool(inv.analysis_results)
        cleared = reset_derived_state(db, inv)
        inv.analysis_started_at = utc_now()
        inv.analysis_completed_at = None
        db.commit()

        if is_rerun:
            add_timeline(db, inv.id, "analysis_restarted",
                         f"Re-analysis started; {cleared} derived artifact(s) from the previous run "
                         "were discarded. The original media and its hash are unchanged.")
        add_timeline(db, inv.id, "analysis_started", "Full analysis pipeline started.")

        # 1 ── Metadata & provenance fields
        set_progress(db, inv, "Extracting metadata", 5)
        probe = probe_media(inv.file_path)
        probe_summary = summarize_probe(probe)
        metadata = _stage_metadata(db, inv, probe_summary)

        # 2 ── Frame sampling
        set_progress(db, inv, "Sampling frames", 15)
        frame_items = _stage_frames(db, inv)

        # 3 ── Audio extraction & forensics
        set_progress(db, inv, "Analysing audio", 30)
        audio_path, audio_result = _stage_audio(db, inv, probe)

        # 4 ── Manipulation detection
        set_progress(db, inv, "Detecting manipulation", 45)
        deepfake_result = _stage_deepfake(db, inv, frame_items)

        # 5 ── Localization
        set_progress(db, inv, "Localizing manipulation", 60)
        localization_result = _stage_localization(db, inv, deepfake_result)

        # 6 ── Identity comparison
        set_progress(db, inv, "Comparing identity", 70)
        identity_result = _stage_identity(db, inv, frame_items)

        # 7 ── Voice comparison
        set_progress(db, inv, "Verifying speaker", 78)
        voice_result = _stage_voice(db, inv, audio_path)

        # 8 ── A/V consistency
        set_progress(db, inv, "Checking A/V consistency", 84)
        consistency_result = _stage_consistency(db, inv, frame_items, audio_path, probe_summary)

        # 9 ── Provenance / C2PA
        set_progress(db, inv, "Reading Content Credentials", 88)
        provenance_result = _stage_provenance(db, inv)

        # 10 ── Local copy tracing
        set_progress(db, inv, "Tracing copies in local index", 92)
        propagation_result = _stage_similarity(db, inv)

        # 11 ── Risk fusion
        set_progress(db, inv, "Fusing risk signals", 96)
        _stage_risk(db, inv, deepfake=deepfake_result, identity=identity_result,
                    voice=voice_result, consistency=consistency_result, audio=audio_result,
                    propagation=propagation_result, provenance=provenance_result,
                    localization=localization_result, metadata=metadata)

        # 12 ── Preservation summary
        preserved = db.query(Evidence).filter(Evidence.investigation_id == inv.id).count()
        add_timeline(db, inv.id, "evidence_preserved",
                     f"{preserved} evidence artifact(s) preserved with SHA-256 digests.")

        inv.status = "completed"
        inv.analysis_completed_at = utc_now()
        set_progress(db, inv, "Completed", 100)
        add_timeline(db, inv.id, "analysis_completed", "Full analysis pipeline completed.")

    except Exception as error:
        print(f"Analysis error: {error}")
        import traceback

        traceback.print_exc()
        db.rollback()
        inv = db.query(Investigation).filter(Investigation.id == investigation_id).first()
        if inv:
            inv.status = "failed"
            inv.error_message = str(error)[:400]
            inv.progress_stage = "Failed"
            db.commit()
            add_timeline(db, inv.id, "analysis_failed", f"Analysis failed: {str(error)[:300]}")
    finally:
        db.close()


def _stage_metadata(db: Session, inv: Investigation, probe_summary: dict) -> dict:
    try:
        metadata = collect_media_metadata(inv.file_path, inv.media_type)
    except Exception as error:
        print(f"Metadata extraction error: {error}")
        metadata = {
            "status": "unavailable",
            "reason": f"Metadata extraction failed: {str(error)[:200]}",
            "media_type": inv.media_type,
        }
        record_result(db, inv.id, "metadata", metadata, status="unavailable")
        add_timeline(db, inv.id, "metadata_extracted",
                     "Metadata extraction failed; container details are unavailable.")
        return metadata

    metadata["status"] = "completed"
    inv.media_metadata = metadata
    if probe_summary:
        inv.duration_seconds = probe_summary.get("duration_seconds") or inv.duration_seconds
        inv.resolution = probe_summary.get("resolution") or inv.resolution
        inv.fps = probe_summary.get("frame_rate") or inv.fps
        inv.has_audio_stream = probe_summary.get("has_audio")
    db.commit()

    record_result(db, inv.id, "metadata", metadata, status="completed")
    descriptors = [
        probe_summary.get("container"),
        probe_summary.get("video_codec"),
        probe_summary.get("resolution"),
        f"{probe_summary['duration_seconds']:.1f}s" if probe_summary.get("duration_seconds") else None,
    ]
    detail = ", ".join(str(d) for d in descriptors if d) or "file-level attributes only"
    add_timeline(db, inv.id, "metadata_extracted", f"Metadata extracted: {detail}.")
    return metadata


def _stage_frames(db: Session, inv: Investigation) -> list[dict]:
    if inv.media_type != "video":
        return []
    try:
        frames_dir = os.path.join(FRAMES_DIR, str(inv.id))
        frame_items = extract_sampled_frames(inv.file_path, frames_dir, FRAME_SAMPLES)
    except Exception as error:
        print(f"Frame sampling error: {error}")
        add_timeline(db, inv.id, "frames_sampled", f"Frame sampling failed: {str(error)[:200]}")
        return []

    for item in frame_items:
        db.add(Evidence(
            investigation_id=inv.id,
            evidence_type="frame",
            file_path=item["path"],
            sha256_hash=calculate_sha256(item["path"]),
            perceptual_hash=calculate_perceptual_hash(item["path"]),
            timestamp_offset=item["timestamp"],
            metadata_json={"frame_index": item["index"], "source_frame_number": item.get("frame_number")},
        ))
    inv.frames_extracted = len(frame_items)
    db.commit()

    if frame_items:
        span = f"{frame_items[0]['timestamp']:.2f}s–{frame_items[-1]['timestamp']:.2f}s"
        add_timeline(db, inv.id, "frames_sampled",
                     f"{len(frame_items)} frames sampled evenly across the video ({span}) "
                     "and preserved with individual SHA-256 digests.")
    else:
        add_timeline(db, inv.id, "frames_sampled",
                     "No frames could be decoded from this video.")
    return frame_items


def _stage_audio(db: Session, inv: Investigation, probe: dict | None):
    from services.audio import analyze_audio, extract_audio_track

    if inv.media_type == "image":
        payload = {
            "status": "not_applicable",
            "reason": "The submitted media is a still image and carries no audio stream.",
            "method": "Container probe + PCM signal statistics",
        }
        record_result(db, inv.id, "audio", payload, status="not_applicable")
        return None, payload

    audio_path = os.path.join(AUDIO_DIR, str(inv.id), "extracted.wav")
    ok, reason = extract_audio_track(inv.file_path, audio_path)
    if not ok:
        payload = {
            "status": "unavailable",
            "reason": f"No audio track could be decoded from this file: {reason}",
            "method": "Container probe + PCM signal statistics",
            "ffmpeg_available": ffmpeg_available(),
        }
        record_result(db, inv.id, "audio", payload, status="unavailable")
        inv.has_audio_stream = False
        db.commit()
        add_timeline(db, inv.id, "audio_extracted",
                     f"No audio track was extracted: {reason}")
        return None, payload

    digest = calculate_sha256(audio_path)
    db.add(Evidence(
        investigation_id=inv.id,
        evidence_type="audio",
        file_path=audio_path,
        sha256_hash=digest,
        metadata_json={
            "derived_from": os.path.basename(inv.file_path),
            "format": "16 kHz mono PCM WAV",
            "purpose": "Speaker verification, audio forensics and A/V alignment.",
        },
    ))
    inv.has_audio_stream = True
    db.commit()
    add_timeline(db, inv.id, "audio_extracted",
                 f"Audio track extracted to 16 kHz mono PCM and preserved (SHA-256 {(digest or '')[:16]}…).")

    try:
        payload = analyze_audio(audio_path, probe)
    except Exception as error:
        print(f"Audio analysis error: {error}")
        payload = {
            "status": "unavailable",
            "reason": f"Audio forensics failed: {str(error)[:200]}",
            "method": "Container probe + PCM signal statistics",
        }
    record_result(db, inv.id, "audio", payload,
                  score=payload.get("editing_indicator"), status=payload.get("status"))
    if payload.get("status") == "completed":
        add_timeline(db, inv.id, "audio_analysis",
                     f"Audio forensics completed: {payload.get('discontinuity_count', 0)} abrupt "
                     "loudness transition(s) detected.")
    return audio_path, payload


def _stage_deepfake(db: Session, inv: Investigation, frame_items: list[dict]) -> dict | None:
    from services.deepfake import analyze_frames, analyze_image, release_models

    try:
        if inv.media_type == "image":
            result = analyze_image(inv.file_path)
            if result:
                result = {**result, "frames_analyzed": 1,
                          "frames_with_face": 1 if result.get("face_detected") else 0,
                          "suspicious_frame_count": 1 if result.get("suspicious") else 0,
                          "frame_results": [result]}
        elif inv.media_type == "video":
            result = analyze_frames(frame_items) if frame_items else None
        else:
            payload = {
                "status": "not_applicable",
                "reason": "The submitted media is audio only; the face-manipulation detector needs "
                          "visual frames. Audio forensics and speaker verification were run instead.",
                "method": "Unavailable",
            }
            record_result(db, inv.id, "deepfake", payload, status="not_applicable")
            return None

        if not result:
            payload = {
                "status": "unavailable",
                "reason": "No analysable frame was available, so no manipulation score was produced.",
                "method": "Unavailable",
            }
            record_result(db, inv.id, "deepfake", payload, status="unavailable")
            add_timeline(db, inv.id, "manipulation_analysis",
                         "Manipulation analysis produced no score: no analysable frame.")
            return None

        result["status"] = "completed"
        result["threshold"] = 0.5
        result["disclaimer"] = (
            "This is a manipulation indicator produced by a research model, not a verdict. "
            "DeepTrace does not claim perfect deepfake detection."
        )
        # Confidence is the model's distance from its own decision boundary, not a
        # copy of the score — the two mean different things to an investigator.
        signal = float(result["manipulation_signal"])
        confidence = None if result.get("method") == "Lightweight fallback" else abs(signal - 0.5) * 2
        record_result(db, inv.id, "deepfake", result, score=signal,
                      confidence=confidence, status="completed")

        summary = f"{result.get('model_name')} scored {signal:.3f}"
        if result.get("frames_analyzed"):
            summary += (f" as the mean over {result['frames_analyzed']} frame(s); "
                        f"{result.get('suspicious_frame_count', 0)} above threshold")
        add_timeline(db, inv.id, "manipulation_analysis", f"Manipulation analysis: {summary}.")
        return result
    except Exception as error:
        print(f"Deepfake analysis error: {error}")
        payload = {
            "status": "unavailable",
            "reason": f"The manipulation detector failed to run: {str(error)[:200]}",
            "method": "Unavailable",
        }
        record_result(db, inv.id, "deepfake", payload, status="unavailable")
        add_timeline(db, inv.id, "manipulation_analysis",
                     f"Manipulation analysis unavailable: {str(error)[:200]}")
        return None
    finally:
        release_models()


def _stage_localization(db: Session, inv: Investigation, deepfake_result: dict | None) -> dict | None:
    from services.localization import localize

    if not deepfake_result:
        payload = {
            "status": "unavailable",
            "reason": "Localization needs per-frame manipulation scores, which were not produced.",
            "method": "Frame ranking + high-frequency residual overlay",
        }
        record_result(db, inv.id, "localization", payload, status="unavailable")
        return None

    try:
        overlay_dir = os.path.join(LOCALIZATION_DIR, str(inv.id))
        payload = localize(deepfake_result, inv.media_type, overlay_dir)
    except Exception as error:
        print(f"Localization error: {error}")
        payload = {
            "status": "unavailable",
            "reason": f"Localization failed: {str(error)[:200]}",
            "method": "Frame ranking + high-frequency residual overlay",
        }
        record_result(db, inv.id, "localization", payload, status="unavailable")
        return None

    for overlay in payload.get("overlays", []):
        db.add(Evidence(
            investigation_id=inv.id,
            evidence_type="localization",
            file_path=overlay["overlay_path"],
            sha256_hash=calculate_sha256(overlay["overlay_path"]),
            timestamp_offset=overlay.get("timestamp_seconds"),
            metadata_json={
                "rank": overlay["rank"],
                "manipulation_signal": overlay["manipulation_signal"],
                "source_frame": os.path.basename(overlay["source_frame"]),
                "visualisation": "High-frequency residual overlay (explainable forensic aid, "
                                 "not a trained segmentation mask).",
            },
        ))
    db.commit()

    record_result(db, inv.id, "localization", payload,
                  score=None, status=payload.get("status"))
    add_timeline(db, inv.id, "localization", f"Manipulation localization: {payload.get('summary')}")
    return payload


def _stage_identity(db: Session, inv: Investigation, frame_items: list[dict]) -> dict | None:
    from services.identity import compare_faces, generate_face_embedding, release_models

    if not inv.identity_id:
        payload = {
            "status": "not_applicable",
            "reason": "No protected identity was attached to this case, so no face comparison was "
                      "performed. Attach an enrolled identity to assess impersonation.",
            "method": "Unavailable",
        }
        record_result(db, inv.id, "identity", payload, status="not_applicable")
        return None

    identity = db.query(Identity).filter(Identity.id == inv.identity_id).first()
    if not identity or not identity.face_embedding:
        payload = {
            "status": "unavailable",
            "reason": "The linked identity has no stored face template, so no comparison was possible.",
            "method": "Unavailable",
        }
        record_result(db, inv.id, "identity", payload, status="unavailable")
        return None

    if inv.media_type == "audio":
        payload = {
            "status": "not_applicable",
            "reason": "The submitted media is audio only; face comparison needs visual frames. "
                      "Speaker verification covers identity for this media type.",
            "method": "Unavailable",
        }
        record_result(db, inv.id, "identity", payload, status="not_applicable")
        return None

    try:
        reference_dimensions = len(identity.face_embedding)
        using_facenet = reference_dimensions == 512
        comparisons: list[dict] = []
        dimension_mismatch = False

        targets = ([{"path": inv.file_path, "timestamp": None, "index": 0}]
                   if inv.media_type == "image" else frame_items)
        for item in targets:
            path = item["path"]
            embedding = generate_face_embedding(path)
            if not embedding:
                comparisons.append({
                    "frame_path": to_public_path(path) or os.path.basename(path),
                    "timestamp_seconds": item.get("timestamp"),
                    "similarity": None,
                    "face_detected": False,
                })
                continue
            if len(embedding) != reference_dimensions:
                dimension_mismatch = True
            similarity = compare_faces(identity.face_embedding, embedding)
            comparisons.append({
                "frame_path": to_public_path(path) or os.path.basename(path),
                "timestamp_seconds": item.get("timestamp"),
                "similarity": round(similarity, 6),
                "face_detected": True,
            })

        scored = [c for c in comparisons if c["similarity"] is not None]
        if not scored:
            payload = {
                "status": "unavailable",
                "reason": (
                    "No face could be detected in the submitted media, so it could not be compared "
                    f"to {identity.name}."
                ),
                "reference_identity": identity.name,
                "frames_examined": len(comparisons),
                "method": "FaceNet InceptionResnetV1 (VGGFace2)" if using_facenet
                          else "Lightweight fallback embedding",
            }
            record_result(db, inv.id, "identity", payload, status="unavailable")
            add_timeline(db, inv.id, "identity_analysis",
                         f"Identity comparison unavailable: no face detected in {len(comparisons)} "
                         "examined frame(s).")
            return None

        similarities = [c["similarity"] for c in scored]
        best = max(similarities)
        average = sum(similarities) / len(similarities)
        threshold = 0.60

        mismatch_note = (
            " The stored reference template and the freshly computed embedding have different "
            "dimensions (fallback 4096-d vs FaceNet 512-d). Re-enroll this identity to refresh it."
            if dimension_mismatch else ""
        )
        if not using_facenet:
            interpretation = (
                "The FaceNet model was unavailable when this identity was enrolled, so the stored "
                "template is a deterministic image embedding. The reported value is a coarse visual "
                "similarity and must NOT be read as a face-identity match."
            )
        elif best >= threshold:
            interpretation = (
                f"Best similarity {best:.3f} is above the {threshold:.2f} same-person threshold for "
                f"VGGFace2 embeddings, consistent with the media depicting {identity.name}."
            )
        else:
            interpretation = (
                f"Best similarity {best:.3f} is below the {threshold:.2f} same-person threshold, so "
                f"the media is not clearly consistent with depicting {identity.name}. A poor "
                "reference image (pose, lighting, resolution) can also produce this."
            )

        payload = {
            "status": "completed",
            "best_similarity": round(best, 6),
            "average_similarity": round(average, 6),
            "threshold": threshold,
            "above_threshold_frames": sum(1 for s in similarities if s >= threshold),
            "frames_analyzed": len(scored),
            "frames_examined": len(comparisons),
            "faces_not_detected": len(comparisons) - len(scored),
            "frame_details": comparisons,
            "reference_identity": identity.name,
            "reference_consent_version": identity.consent_text_version,
            "method": "FaceNet InceptionResnetV1 (VGGFace2)" if using_facenet
                      else "Lightweight fallback embedding",
            "model_status": "Advanced ML model available" if using_facenet
                            else "Advanced ML model unavailable on this machine",
            "model_name": "FaceNet / InceptionResnetV1" if using_facenet else "Lightweight fallback",
            "model_version": "pretrained VGGFace2" if using_facenet
                             else "deterministic image embedding",
            "embedding_dimensions": reference_dimensions,
            "dimension_mismatch": dimension_mismatch,
            "interpretation": interpretation + mismatch_note,
            "note": "Cosine similarity of face embeddings. Supporting identity evidence, not proof "
                    "of identity.",
        }
        record_result(db, inv.id, "identity", payload, score=best,
                      confidence=round(average, 6), status="completed")
        add_timeline(db, inv.id, "identity_analysis",
                     f"Face comparison against {identity.name}: best similarity {best:.3f} across "
                     f"{len(scored)} frame(s) (threshold {threshold:.2f}).")
        return payload
    except Exception as error:
        print(f"Identity analysis error: {error}")
        payload = {
            "status": "unavailable",
            "reason": f"Face comparison failed to run: {str(error)[:200]}",
            "method": "Unavailable",
        }
        record_result(db, inv.id, "identity", payload, status="unavailable")
        return None
    finally:
        release_models()


def _stage_voice(db: Session, inv: Investigation, audio_path: str | None) -> dict | None:
    from services.voice import release_models, verify_speaker

    try:
        identity = (db.query(Identity).filter(Identity.id == inv.identity_id).first()
                    if inv.identity_id else None)
        payload = verify_speaker(
            identity.reference_audio_path if identity else None,
            audio_path,
            identity.name if identity else None,
        )
        score = payload.get("voice_match_score")
        record_result(db, inv.id, "voice", payload, score=score,
                      confidence=abs(score) if isinstance(score, (int, float)) else None,
                      status=payload.get("status"))
        if payload.get("status") == "completed":
            add_timeline(db, inv.id, "voice_analysis",
                         f"Speaker verification against {identity.name if identity else 'reference'}: "
                         f"similarity {score:.3f}.")
        else:
            add_timeline(db, inv.id, "voice_analysis",
                         f"Speaker verification not performed: {payload.get('reason')}")
        return payload
    except Exception as error:
        print(f"Voice analysis error: {error}")
        payload = {
            "status": "unavailable",
            "reason": f"Speaker verification failed to run: {str(error)[:200]}",
            "method": "Unavailable",
        }
        record_result(db, inv.id, "voice", payload, status="unavailable")
        return None
    finally:
        release_models()


def _stage_consistency(db: Session, inv: Investigation, frame_items: list[dict],
                       audio_path: str | None, probe_summary: dict) -> dict | None:
    from services.consistency import check_av_consistency

    if inv.media_type != "video":
        payload = {
            "status": "not_applicable",
            "consistency_score": None,
            "details": f"A/V consistency applies to video; this case holds {inv.media_type} media.",
            "method": "Face presence vs audio RMS windows + stream duration agreement",
        }
        record_result(db, inv.id, "consistency", payload, status="not_applicable")
        return None

    try:
        payload = check_av_consistency(inv.file_path, frame_items, audio_path, probe_summary)
    except Exception as error:
        print(f"Consistency analysis error: {error}")
        payload = {
            "status": "unavailable",
            "consistency_score": None,
            "details": f"A/V consistency failed to run: {str(error)[:200]}",
            "method": "Face presence vs audio RMS windows + stream duration agreement",
        }

    record_result(db, inv.id, "consistency", payload,
                  score=payload.get("consistency_score"), status=payload.get("status"))
    if payload.get("status") == "completed":
        add_timeline(db, inv.id, "av_consistency",
                     f"A/V consistency: {payload['consistency_score'] * 100:.0f}% alignment across "
                     f"{payload.get('samples_compared')} sampled timestamps.")
    else:
        add_timeline(db, inv.id, "av_consistency",
                     f"A/V consistency not measured: {payload.get('details')}")
    return payload


def _stage_provenance(db: Session, inv: Investigation) -> dict | None:
    from services.provenance import inspect_c2pa

    try:
        payload = inspect_c2pa(inv.file_path)
    except Exception as error:
        print(f"Provenance analysis error: {error}")
        payload = {
            "status": f"C2PA inspection failed: {str(error)[:200]}",
            "credentials_found": False,
            "method": "c2pa-python",
        }
    payload.setdefault("credentials_found", False)
    record_result(db, inv.id, "provenance", payload,
                  status="completed" if payload.get("credentials_found") else "no_credentials")
    add_timeline(db, inv.id, "provenance_check",
                 "Content Credentials present and read." if payload.get("credentials_found")
                 else "No Content Credentials are attached to this file (normal for most media).")
    return payload


def _collect_hash_items(rows) -> list[dict]:
    return [
        {
            "evidence_id": row.id,
            "investigation_id": row.investigation_id,
            "evidence_type": row.evidence_type,
            "sha256": row.sha256_hash,
            "perceptual_hash": row.perceptual_hash,
            "timestamp_offset": row.timestamp_offset,
        }
        for row in rows
    ]


def _stage_similarity(db: Session, inv: Investigation) -> dict | None:
    from services.similarity import MAX_INDEX_ROWS, find_local_copies

    try:
        mine = db.query(Evidence).filter(Evidence.investigation_id == inv.id).all()
        others = (db.query(Evidence)
                  .filter(Evidence.investigation_id != inv.id)
                  .limit(MAX_INDEX_ROWS)
                  .all())
        titles = {
            row.id: row.filename
            for row in db.query(Investigation.id, Investigation.filename).all()
        }
        payload = find_local_copies(_collect_hash_items(mine), _collect_hash_items(others), titles)
    except Exception as error:
        print(f"Local copy tracing error: {error}")
        payload = {
            "status": "unavailable",
            "reason": f"Local copy tracing failed: {str(error)[:200]}",
            "matches": [],
            "match_count": 0,
        }

    record_result(db, inv.id, "similarity", payload,
                  score=payload.get("best_similarity"), status=payload.get("status"))
    add_timeline(db, inv.id, "similarity_search",
                 payload.get("summary") or "Local copy tracing completed.")
    return payload


def _stage_risk(db: Session, inv: Investigation, *, metadata: dict | None, **signals) -> None:
    from services.risk import fuse

    identity_name = inv.identity.name if inv.identity else None
    payload = fuse(media_type=inv.media_type, identity_name=identity_name, **signals)
    payload["metadata_status"] = (metadata or {}).get("status")

    inv.overall_risk_score = payload["overall_risk_score"]
    inv.risk_level = payload["risk_level"]
    db.commit()

    record_result(db, inv.id, "risk_fusion", payload,
                  score=payload["overall_risk_score"], status="completed")
    add_timeline(db, inv.id, "risk_assessment",
                 f"Risk assessed {payload['risk_level']} ({payload['overall_risk_score']:.2f}) from "
                 f"{payload['signals_used']} available signal(s); {payload['signals_excluded']} "
                 "excluded as unavailable.")


# ─── Timeline, evidence, integrity ───────────────────────────────────────────

@app.get("/api/investigation/{investigation_id}/timeline")
def get_timeline(investigation_id: int, db: Session = Depends(get_db)):
    get_investigation_or_404(db, investigation_id)
    events = (db.query(TimelineEvent)
              .filter(TimelineEvent.investigation_id == investigation_id)
              .order_by(TimelineEvent.created_at.asc(), TimelineEvent.id.asc())
              .all())
    return [
        {
            "id": event.id,
            "event_type": event.event_type,
            "description": event.description,
            "created_at": str(event.created_at) if event.created_at else None,
        }
        for event in events
    ]


@app.get("/api/investigation/{investigation_id}/evidence")
def get_evidence(investigation_id: int, db: Session = Depends(get_db)):
    get_investigation_or_404(db, investigation_id)
    items = (db.query(Evidence)
             .filter(Evidence.investigation_id == investigation_id)
             .order_by(Evidence.evidence_type.asc(), Evidence.id.asc())
             .all())
    return [evidence_payload(item) for item in items]


@app.get("/api/investigation/{investigation_id}/verify")
def verify_evidence(investigation_id: int, db: Session = Depends(get_db)):
    """Re-hash every preserved artifact and compare against the recorded digest."""
    from services.integrity import verify_investigation

    inv = get_investigation_or_404(db, investigation_id)
    items = (db.query(Evidence)
             .filter(Evidence.investigation_id == investigation_id)
             .order_by(Evidence.id.asc())
             .all())
    payload = verify_investigation([
        {
            "id": item.id,
            "evidence_type": item.evidence_type,
            "file_path": item.file_path,
            "sha256_hash": item.sha256_hash,
            "public_path": to_public_path(item.file_path),
            "timestamp_offset": item.timestamp_offset,
            "created_at": str(item.created_at) if item.created_at else None,
        }
        for item in items
    ])
    payload["investigation_id"] = inv.id

    add_timeline(db, inv.id, "integrity_verified",
                 f"Integrity re-verification: {payload['summary']}")
    return payload


@app.get("/api/investigation/{investigation_id}/custody")
def get_custody_record(investigation_id: int, db: Session = Depends(get_db)):
    """The chain-of-custody record, plus the hash-versus-analysis boundary.

    Deliberately does not write a timeline event: this is a rendering of the
    record, and logging every read would pollute the chronology it displays.
    """
    from services.custody import build_custody_record
    from services.integrity import verify_investigation

    inv = get_investigation_or_404(db, investigation_id)
    integrity = verify_investigation([
        {
            "id": item.id,
            "evidence_type": item.evidence_type,
            "file_path": item.file_path,
            "sha256_hash": item.sha256_hash,
            "public_path": to_public_path(item.file_path),
            "timestamp_offset": item.timestamp_offset,
            "created_at": str(item.created_at) if item.created_at else None,
        }
        for item in inv.evidence_items
    ])
    identity = (db.query(Identity).filter(Identity.id == inv.identity_id).first()
                if inv.identity_id else None)
    return build_custody_record(inv, integrity, identity)


# ─── Public-source tracing ───────────────────────────────────────────────────

@app.get("/api/investigation/{investigation_id}/trace")
def get_trace(investigation_id: int, db: Session = Depends(get_db)):
    inv = get_investigation_or_404(db, investigation_id)
    sources = [trace_payload(source) for source in inv.trace_sources]
    fetched = [s for s in sources if s["retrieval_status"] == "fetched"]
    return {
        "investigation_id": inv.id,
        "source_count": len(sources),
        "retrieved_count": len(fetched),
        "sources": sources,
        "scope": (
            "DeepTrace retrieves only the specific public HTTPS URLs an investigator supplies. It "
            "does not search the internet, does not access private or authenticated APIs, and does "
            "not bypass any access control."
        ),
    }


@app.post("/api/investigation/{investigation_id}/trace")
async def run_trace(
    investigation_id: int,
    source_urls: str = Form(None),
    local_copy: UploadFile = File(None),
    label: str = Form(None),
    db: Session = Depends(get_db),
):
    """Attach and compare an external copy.

    Two supported inputs: a public HTTPS URL DeepTrace retrieves itself, or a copy
    the investigator already holds and uploads. Both are preserved with hashes and
    compared to the case original.
    """
    from services.tracing import classify_copy, fetch_public_url, parse_source_urls
    from services.forensics import audio_fingerprint

    inv = get_investigation_or_404(db, investigation_id)
    requested = parse_source_urls(source_urls)
    has_local = bool(local_copy and local_copy.filename)
    if not requested and not has_local:
        raise HTTPException(
            status_code=422,
            detail="Provide at least one public https:// URL or upload a local copy to compare.",
        )

    original_fingerprint = None
    if inv.media_type in {"audio", "video"}:
        audio_artifact = (db.query(Evidence)
                          .filter(Evidence.investigation_id == inv.id, Evidence.evidence_type == "audio")
                          .first())
        candidate = audio_artifact.file_path if audio_artifact else (
            inv.file_path if inv.media_type == "audio" else None)
        if candidate and os.path.isfile(candidate):
            original_fingerprint = audio_fingerprint(candidate)

    sources_dir = os.path.join(SOURCES_DIR, str(inv.id))
    created: list[TraceSource] = []
    existing = {source.source_url: source for source in inv.trace_sources if source.source_url}

    for url in requested:
        outcome = fetch_public_url(url, sources_dir)
        record = existing.get(url)
        if record is None:
            record = TraceSource(investigation_id=inv.id, source_url=url)
            db.add(record)
        record.origin = "public_url"
        record.retrieval_status = outcome["status"]
        record.retrieval_error = outcome.get("error")
        record.title = label or record.title

        if outcome["status"] == "fetched":
            comparison = classify_copy(inv.sha256_hash, inv.perceptual_hash,
                                       original_fingerprint, outcome["file_path"], inv.media_type)
            record.file_path = outcome["file_path"]
            record.content_type = outcome.get("content_type")
            record.bytes_downloaded = outcome.get("bytes")
            record.sha256_hash = comparison["sha256"]
            record.perceptual_hash = comparison["perceptual_hash"]
            record.similarity = comparison["similarity"]
            record.match_type = comparison["match_type"]
            record.similarity_label = comparison["similarity_label"]
            record.details = {
                "basis": comparison["basis"],
                "audio_fingerprint_similarity": comparison["audio_fingerprint_similarity"],
                "retrieved_at": utc_now().isoformat(timespec="seconds"),
                "method": "Direct HTTPS GET of the supplied URL; size-capped and streamed to disk.",
            }
            db.commit()
            db.add(Evidence(
                investigation_id=inv.id,
                evidence_type="traced_copy",
                file_path=outcome["file_path"],
                sha256_hash=comparison["sha256"],
                perceptual_hash=comparison["perceptual_hash"],
                metadata_json={
                    "source_url": url,
                    "content_type": outcome.get("content_type"),
                    "bytes": outcome.get("bytes"),
                    "match_type": comparison["match_type"],
                    "similarity": comparison["similarity"],
                },
            ))
            db.commit()
            add_timeline(db, inv.id, "source_traced",
                         f"Retrieved a copy from {url}: {comparison['similarity_label']} "
                         f"({comparison['basis']})")
        else:
            record.details = {
                "attempted_at": utc_now().isoformat(timespec="seconds"),
                "method": "Direct HTTPS GET of the supplied URL.",
            }
            db.commit()
            add_timeline(db, inv.id, "source_trace_failed",
                         f"Could not retrieve {url}: {outcome.get('error')}")
        created.append(record)

    if has_local:
        extension = os.path.splitext(safe_filename(local_copy.filename))[1].lower()
        if extension not in MEDIA_TYPES:
            raise HTTPException(status_code=415,
                                detail="The uploaded copy must be an image, video or audio file.")
        copy_path, copy_size, _ = store_upload(local_copy, sources_dir, MAX_UPLOAD_BYTES, MAX_UPLOAD_MB)
        comparison = classify_copy(inv.sha256_hash, inv.perceptual_hash, original_fingerprint,
                                   copy_path, inv.media_type)
        record = TraceSource(
            investigation_id=inv.id,
            source_url=None,
            title=label or safe_filename(local_copy.filename),
            description="Copy supplied directly by the investigator.",
            origin="local_copy",
            retrieval_status="fetched",
            file_path=copy_path,
            bytes_downloaded=copy_size,
            sha256_hash=comparison["sha256"],
            perceptual_hash=comparison["perceptual_hash"],
            similarity=comparison["similarity"],
            match_type=comparison["match_type"],
            similarity_label=comparison["similarity_label"],
            details={
                "basis": comparison["basis"],
                "audio_fingerprint_similarity": comparison["audio_fingerprint_similarity"],
                "received_at": utc_now().isoformat(timespec="seconds"),
                "method": "Investigator-supplied upload; hashed server-side on write.",
            },
        )
        db.add(record)
        db.commit()
        db.add(Evidence(
            investigation_id=inv.id,
            evidence_type="traced_copy",
            file_path=copy_path,
            sha256_hash=comparison["sha256"],
            perceptual_hash=comparison["perceptual_hash"],
            metadata_json={
                "origin": "local_copy",
                "supplied_filename": safe_filename(local_copy.filename),
                "bytes": copy_size,
                "match_type": comparison["match_type"],
                "similarity": comparison["similarity"],
            },
        ))
        db.commit()
        add_timeline(db, inv.id, "source_traced",
                     f"Investigator-supplied copy compared: {comparison['similarity_label']} "
                     f"({comparison['basis']})")
        created.append(record)

    recorded = sorted({url for url in (inv.source_urls or []) + requested if url})
    inv.source_urls = recorded or None
    db.commit()
    db.refresh(inv)

    return {
        "investigation_id": inv.id,
        "processed": len(created),
        "sources": [trace_payload(source) for source in inv.trace_sources],
        "scope": (
            "Only the URLs supplied here were retrieved. DeepTrace performs no internet-wide search "
            "and accesses no private or authenticated endpoint."
        ),
    }


# ─── Similarity, guidance, report ────────────────────────────────────────────

@app.get("/api/investigation/{investigation_id}/similarity")
def get_similarity(investigation_id: int, db: Session = Depends(get_db)):
    inv = get_investigation_or_404(db, investigation_id)
    payload = module_data(inv, "similarity")
    if payload is None:
        return {
            "status": "not_run",
            "reason": "Local copy tracing has not run for this investigation yet.",
            "matches": [],
            "match_count": 0,
        }
    return payload


@app.get("/api/investigation/{investigation_id}/response-guidance")
def get_response_guidance(investigation_id: int, db: Session = Depends(get_db)):
    """Case-specific next steps, generated from this case's own findings."""
    from services.integrity import verify_investigation
    from services.response import build_guidance

    inv = get_investigation_or_404(db, investigation_id)
    if inv.status != "completed":
        raise HTTPException(
            status_code=409,
            detail="Response guidance is generated from completed analysis results. "
                   f"This investigation is currently '{inv.status}'.",
        )

    results = module_results(inv)
    integrity = verify_investigation([
        {
            "id": item.id,
            "evidence_type": item.evidence_type,
            "file_path": item.file_path,
            "sha256_hash": item.sha256_hash,
        }
        for item in inv.evidence_items
    ])

    return {
        "investigation_id": inv.id,
        "generated_at": utc_now().isoformat(timespec="seconds"),
        **build_guidance(
            investigation={
                "id": inv.id,
                "filename": inv.filename,
                "media_type": inv.media_type,
                "risk_level": inv.risk_level,
                "frames_extracted": inv.frames_extracted,
            },
            risk=(results.get("risk_fusion") or {}).get("data"),
            deepfake=(results.get("deepfake") or {}).get("data"),
            identity=(results.get("identity") or {}).get("data"),
            voice=(results.get("voice") or {}).get("data"),
            localization=(results.get("localization") or {}).get("data"),
            propagation=(results.get("similarity") or {}).get("data"),
            provenance=(results.get("provenance") or {}).get("data"),
            trace_sources=[trace_payload(source) for source in inv.trace_sources],
            integrity=integrity,
        ),
    }


@app.get("/api/investigation/{investigation_id}/report")
def generate_report_endpoint(investigation_id: int, db: Session = Depends(get_db)):
    """Generate the forensic incident report PDF."""
    from services.report import generate_report

    get_investigation_or_404(db, investigation_id)
    try:
        path = generate_report(investigation_id, db)
    except Exception as error:
        print(f"Report generation error: {error}")
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500,
                            detail="The report could not be generated. Check the server log.") from error
    if not path:
        raise HTTPException(status_code=404, detail="Investigation not found")

    digest = calculate_sha256(path)
    add_timeline(db, investigation_id, "report_generated",
                 f"Forensic incident report generated (SHA-256 {(digest or '')[:16]}…).")
    return {
        "status": "generated",
        "report_path": repo_relative(path),
        "filename": os.path.basename(path),
        "sha256": digest,
        "download_url": f"/api/report/{investigation_id}/download",
    }


@app.get("/api/report/{investigation_id}/download")
def download_report(investigation_id: int):
    path = report_path(investigation_id)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Report not found. Generate it first.")
    return FileResponse(path, media_type="application/pdf", filename=os.path.basename(path))


# ─── Dashboard, demo assets, benchmark ───────────────────────────────────────

@app.get("/api/dashboard/stats")
def dashboard_stats(db: Session = Depends(get_db)):
    return {
        "active_investigations": db.query(Investigation).count(),
        "evidence_items": db.query(Evidence).count(),
        "high_risk_findings": db.query(Investigation)
                                .filter(Investigation.risk_level.in_(["HIGH", "CRITICAL"])).count(),
        "protected_identities": db.query(Identity).count(),
    }


@app.get("/api/demo/assets")
def demo_assets():
    """List the demo inputs shipped in ``data/demo``.

    These are demo *inputs* only. Every score, hash, timestamp and finding shown
    for them is produced by running the real pipeline over them.
    """
    if not os.path.isdir(DEMO_DIR):
        return {"available": False, "assets": [],
                "reason": "No data/demo directory is present in this checkout."}

    assets = []
    for name in sorted(os.listdir(DEMO_DIR)):
        full = os.path.join(DEMO_DIR, name)
        if not os.path.isfile(full):
            continue
        extension = os.path.splitext(name)[1].lower()
        if extension not in MEDIA_TYPES:
            continue
        assets.append({
            "filename": name,
            "media_type": MEDIA_TYPES[extension],
            "size_bytes": os.path.getsize(full),
            "url": f"/demo-assets/{name}",
        })
    return {
        "available": bool(assets),
        "count": len(assets),
        "assets": assets,
        "note": "Demo files are inputs. All analysis output for them is computed live by the pipeline.",
    }


@app.get("/api/benchmark")
def benchmark_results():
    """Return the last stored benchmark run, if one has been executed."""
    latest = os.path.join(BENCHMARK_DIR, "latest.json")
    if not os.path.isfile(latest):
        return {
            "available": False,
            "reason": (
                "No benchmark has been run in this environment. Run scripts/benchmark.py against a "
                "labelled dataset to produce metrics. DeepTrace does not ship pre-computed accuracy "
                "figures."
            ),
        }
    try:
        with open(latest, "r", encoding="utf-8") as handle:
            return {"available": True, **json.load(handle)}
    except Exception as error:
        return {"available": False, "reason": f"The stored benchmark file could not be read: {error}"}
