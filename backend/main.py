from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from datetime import datetime
import os
import shutil
import json
from uuid import uuid4

from database import engine, Base, get_db, migrate_sqlite
from models.schema import Identity, Investigation, Evidence, AnalysisResult, TimelineEvent
from services.forensics import calculate_sha256, extract_video_metadata, calculate_perceptual_hash

# Create tables
Base.metadata.create_all(bind=engine)
migrate_sqlite()

app = FastAPI(title="DeepTrace API", version="1.0.0", description="Intelligent Digital Impersonation Detection and Forensic Evidence Preservation")

# Allow CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
EVIDENCE_DIR = "evidence"
DATA_DIR = "data"
PROJECT_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(EVIDENCE_DIR, exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "reports"), exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "demo"), exist_ok=True)

# Mount static files for serving frames/evidence
app.mount("/evidence", StaticFiles(directory=EVIDENCE_DIR), name="evidence")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
if os.path.isdir(PROJECT_DATA_DIR):
    app.mount("/demo-assets", StaticFiles(directory=PROJECT_DATA_DIR), name="demo-assets")

# ─── Health ─────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "DeepTrace", "version": "1.0.0"}

@app.get("/")
def read_root():
    return {"status": "DeepTrace Backend Running", "docs": "/docs"}

# ─── Identity Endpoints ────────────────────────────────

@app.post("/api/identity/enroll")
async def enroll_identity(
    name: str = Form(...),
    reference_image: UploadFile = File(...),
    reference_audio: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    """Enroll a protected identity profile with face embedding."""
    name = name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Identity name is required.")
    if not reference_image.filename:
        raise HTTPException(status_code=422, detail="A reference image is required.")

    # Save reference image
    os.makedirs(os.path.join(UPLOAD_DIR, "identities"), exist_ok=True)
    image_filename = os.path.basename(reference_image.filename)
    img_path = os.path.join(UPLOAD_DIR, "identities", f"{uuid4().hex}_{image_filename}")
    with open(img_path, "wb") as f:
        shutil.copyfileobj(reference_image.file, f)
    
    # Generate face embedding
    face_embedding = None
    try:
        from services.identity import generate_face_embedding
        face_embedding = generate_face_embedding(img_path)
    except Exception as e:
        print(f"Face embedding error: {e}")
    
    if face_embedding is None:
        try:
            os.remove(img_path)
        except OSError:
            pass
        raise HTTPException(status_code=400, detail="No face detected in the reference image. Please upload a clear frontal face photo.")
    
    # Save reference audio if provided
    audio_path = None
    voice_embedding = None
    if reference_audio and reference_audio.filename:
        audio_filename = os.path.basename(reference_audio.filename)
        audio_path = os.path.join(UPLOAD_DIR, "identities", f"{uuid4().hex}_{audio_filename}")
        with open(audio_path, "wb") as f:
            shutil.copyfileobj(reference_audio.file, f)
        try:
            from services.voice import generate_voice_embedding
            voice_embedding = generate_voice_embedding(audio_path)
        except Exception as e:
            print(f"Voice embedding error: {e}")
    
    identity = Identity(
        name=name,
        reference_image_path=img_path,
        reference_audio_path=audio_path,
        face_embedding=face_embedding,
        voice_embedding=voice_embedding,
    )
    try:
        db.add(identity)
        db.commit()
        db.refresh(identity)
    except Exception as e:
        db.rollback()
        for path in (img_path, audio_path):
            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass
        raise HTTPException(status_code=500, detail="Could not save the identity profile. Please try again.") from e
    
    return {
        "id": identity.id,
        "name": identity.name,
        "face_enrolled": face_embedding is not None,
        "voice_enrolled": voice_embedding is not None,
        "created_at": str(identity.created_at),
    }

@app.get("/api/identities")
def list_identities(db: Session = Depends(get_db)):
    identities = db.query(Identity).all()
    return [
        {
            "id": i.id,
            "name": i.name,
            "face_enrolled": i.face_embedding is not None,
            "voice_enrolled": i.voice_embedding is not None,
            "created_at": str(i.created_at),
            "reference_image_path": i.reference_image_path,
        }
        for i in identities
    ]

@app.get("/api/identity/{identity_id}")
def get_identity(identity_id: int, db: Session = Depends(get_db)):
    identity = db.query(Identity).filter(Identity.id == identity_id).first()
    if not identity:
        raise HTTPException(status_code=404, detail="Identity not found")
    return {
        "id": identity.id,
        "name": identity.name,
        "face_enrolled": identity.face_embedding is not None,
        "voice_enrolled": identity.voice_embedding is not None,
        "created_at": str(identity.created_at),
        "reference_image_path": identity.reference_image_path,
    }

# ─── Investigation Endpoints ──────────────────────────

@app.post("/api/investigate")
async def create_investigation(
    file: UploadFile = File(...),
    identity_id: int = Form(None),
    db: Session = Depends(get_db)
):
    """Upload suspicious media and create an investigation."""
    if not file.filename:
        raise HTTPException(status_code=422, detail="A media file is required.")

    filename = os.path.basename(file.filename)
    ext = os.path.splitext(filename)[1].lower()
    media_types = {
        ".mp4": "video", ".avi": "video", ".mov": "video", ".mkv": "video", ".webm": "video",
        ".jpg": "image", ".jpeg": "image", ".png": "image", ".bmp": "image", ".webp": "image",
        ".wav": "audio", ".mp3": "audio", ".flac": "audio", ".ogg": "audio",
    }
    media_type = media_types.get(ext)
    if media_type is None:
        raise HTTPException(status_code=415, detail="Unsupported media type. Upload an image, video, or audio file.")
    if identity_id is not None and not db.query(Identity.id).filter(Identity.id == identity_id).first():
        raise HTTPException(status_code=422, detail="The selected protected identity no longer exists.")

    file_path = os.path.join(UPLOAD_DIR, f"{uuid4().hex}_{filename}")
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    file_size = os.path.getsize(file_path)
    sha256_hash = calculate_sha256(file_path)
    
    investigation = Investigation(
        filename=filename,
        file_path=file_path,
        file_size_bytes=file_size,
        sha256_hash=sha256_hash,
        media_type=media_type,
        identity_id=identity_id,
        status="pending",
    )
    
    if media_type == "video":
        metadata = extract_video_metadata(file_path)
        if metadata:
            investigation.duration_seconds = metadata["duration_seconds"]
            investigation.resolution = metadata["resolution"]
            investigation.fps = metadata["fps"]
            investigation.frames_extracted = metadata["frames_extracted"]
    
    db.add(investigation)
    db.commit()
    db.refresh(investigation)
    
    # Record timeline
    _add_timeline(db, investigation.id, "investigation_created", f"Investigation created for {file.filename}")
    _add_timeline(db, investigation.id, "evidence_uploaded", f"File uploaded: {file.filename} ({file_size} bytes)")
    _add_timeline(db, investigation.id, "hash_generated", f"SHA-256: {sha256_hash}")
    
    # Store original as evidence
    evidence = Evidence(
        investigation_id=investigation.id,
        evidence_type="original",
        file_path=file_path,
        sha256_hash=sha256_hash,
        perceptual_hash=calculate_perceptual_hash(file_path) if media_type == "image" else None,
    )
    db.add(evidence)
    db.commit()
    
    return {
        "message": "Investigation created successfully",
        "id": investigation.id,
        "status": investigation.status,
        "media_type": media_type,
        "sha256": sha256_hash,
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
            "risk_level": inv.risk_level,
            "created_at": str(inv.created_at),
            "identity_id": inv.identity_id,
        }
        for inv in investigations
    ]

@app.get("/api/investigation/{investigation_id}")
def get_investigation(investigation_id: int, db: Session = Depends(get_db)):
    inv = db.query(Investigation).filter(Investigation.id == investigation_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")
    
    # Gather analysis results
    results = {}
    for ar in inv.analysis_results:
        results[ar.module_name] = {
            "score": ar.score,
            "confidence": ar.confidence,
            "data": ar.result_data,
            "created_at": str(ar.created_at),
        }
    
    # Gather evidence
    evidence_list = []
    for ev in inv.evidence_items:
        evidence_list.append({
            "id": ev.id,
            "type": ev.evidence_type,
            "file_path": ev.file_path,
            "sha256": ev.sha256_hash,
            "perceptual_hash": ev.perceptual_hash,
            "timestamp_offset": ev.timestamp_offset,
        })
    
    return {
        "id": inv.id,
        "filename": inv.filename,
        "file_path": inv.file_path,
        "file_size_bytes": inv.file_size_bytes,
        "sha256_hash": inv.sha256_hash,
        "media_type": inv.media_type,
        "status": inv.status,
        "identity_id": inv.identity_id,
        "duration_seconds": inv.duration_seconds,
        "resolution": inv.resolution,
        "fps": inv.fps,
        "frames_extracted": inv.frames_extracted,
        "overall_risk_score": inv.overall_risk_score,
        "risk_level": inv.risk_level,
        "created_at": str(inv.created_at),
        "analysis_results": results,
        "evidence": evidence_list,
    }

# ─── Analysis Endpoint ────────────────────────────────

@app.post("/api/investigation/{investigation_id}/analyze")
async def analyze_investigation(investigation_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    inv = db.query(Investigation).filter(Investigation.id == investigation_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")
    
    inv.status = "analyzing"
    db.commit()
    
    background_tasks.add_task(run_analysis, investigation_id)
    
    return {"message": "Analysis started", "id": investigation_id, "status": "analyzing"}

def run_analysis(investigation_id: int):
    """Run the full analysis pipeline in the background."""
    from database import SessionLocal
    db = SessionLocal()
    try:
        inv = db.query(Investigation).filter(Investigation.id == investigation_id).first()
        if not inv:
            return
        
        _add_timeline(db, inv.id, "analysis_started", "Full analysis pipeline started")
        
        # 1) METADATA EXTRACTION
        _add_timeline(db, inv.id, "metadata_extracted", "File metadata extracted")
        
        # 2) FRAME EXTRACTION (for video)
        frame_paths = []
        if inv.media_type == "video":
            frame_paths = _extract_and_store_frames(db, inv)
            _add_timeline(db, inv.id, "frames_sampled", f"Extracted {len(frame_paths)} sampled frames")
        
        # 3) DEEPFAKE / MANIPULATION ANALYSIS
        _run_deepfake_analysis(db, inv, frame_paths)
        _add_timeline(db, inv.id, "manipulation_analysis", "Deepfake/manipulation analysis completed")
        
        # 4) IDENTITY ANALYSIS
        _run_identity_analysis(db, inv, frame_paths)
        _add_timeline(db, inv.id, "identity_analysis", "Identity/face analysis completed")
        
        # 5) VOICE ANALYSIS
        _run_voice_analysis(db, inv)
        _add_timeline(db, inv.id, "audio_analysis", "Audio/voice analysis completed")
        
        # 6) AV CONSISTENCY
        if inv.media_type == "video":
            _run_consistency_analysis(db, inv)

        # 6b) PROVENANCE / C2PA
        _run_provenance_analysis(db, inv)
        
        # 7) SIMILARITY SEARCH
        _run_similarity_search(db, inv)
        _add_timeline(db, inv.id, "similarity_search", "Similarity search against indexed evidence completed")
        
        # 8) RISK FUSION
        _calculate_risk(db, inv)
        _add_timeline(db, inv.id, "risk_assessment", f"Risk assessment: {inv.risk_level}")
        
        # 9) EVIDENCE PRESERVATION
        _add_timeline(db, inv.id, "evidence_preserved", "Evidence artifacts preserved")
        
        inv.status = "completed"
        db.commit()
        
        _add_timeline(db, inv.id, "analysis_completed", "Full analysis pipeline completed")
        
    except Exception as e:
        print(f"Analysis error: {e}")
        import traceback
        traceback.print_exc()
        inv = db.query(Investigation).filter(Investigation.id == investigation_id).first()
        if inv:
            inv.status = "failed"
            db.commit()
            _add_timeline(db, inv.id, "analysis_failed", f"Analysis failed: {str(e)}")
    finally:
        db.close()

def _extract_and_store_frames(db: Session, inv: Investigation) -> list:
    """Extract sampled frames from video and store as evidence."""
    import cv2
    
    cap = cv2.VideoCapture(inv.file_path)
    if not cap.isOpened():
        return []
    
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    frames_dir = os.path.join(EVIDENCE_DIR, "frames", str(inv.id))
    os.makedirs(frames_dir, exist_ok=True)
    
    # Sample up to 10 frames evenly
    num_samples = min(10, max(1, frame_count))
    intervals = [int(i * frame_count / num_samples) for i in range(num_samples)]
    
    frame_paths = []
    for idx, frame_idx in enumerate(intervals):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if ret:
            timestamp = frame_idx / fps if fps > 0 else 0
            frame_path = os.path.join(frames_dir, f"frame_{idx}_{timestamp:.2f}s.jpg")
            cv2.imwrite(frame_path, frame)
            frame_paths.append(frame_path)
            
            phash = calculate_perceptual_hash(frame_path)
            
            ev = Evidence(
                investigation_id=inv.id,
                evidence_type="frame",
                file_path=frame_path,
                sha256_hash=calculate_sha256(frame_path),
                perceptual_hash=phash,
                timestamp_offset=timestamp,
            )
            db.add(ev)
    
    cap.release()
    inv.frames_extracted = len(frame_paths)
    db.commit()
    return frame_paths

def _run_deepfake_analysis(db: Session, inv: Investigation, frame_paths: list):
    """Run deepfake detection on image or video frames."""
    try:
        from services.deepfake import analyze_image, analyze_frames, release_models
        
        if inv.media_type == "image":
            result = analyze_image(inv.file_path)
            if result:
                ar = AnalysisResult(
                    investigation_id=inv.id,
                    module_name="deepfake",
                    score=result["manipulation_signal"],
                    confidence=None if result.get("method") == "Lightweight fallback" else result["manipulation_signal"],
                    result_data={
                        **result,
                        "model_name": result.get("model_name", "Hemg/Deepfake-Detection"),
                        "model_version": result.get("model_version", "pretrained Hugging Face checkpoint"),
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )
                db.add(ar)
                db.commit()
        elif inv.media_type == "video" and frame_paths:
            result = analyze_frames(frame_paths)
            if result:
                ar = AnalysisResult(
                    investigation_id=inv.id,
                    module_name="deepfake",
                    score=result["manipulation_signal"],
                    confidence=None if result.get("method") == "Lightweight fallback" else result["manipulation_signal"],
                    result_data={
                        **result,
                        "model_name": result.get("model_name", "Hemg/Deepfake-Detection"),
                        "model_version": result.get("model_version", "pretrained Hugging Face checkpoint"),
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )
                db.add(ar)
                db.commit()
        
        release_models()
    except Exception as e:
        print(f"Deepfake analysis error: {e}")
        ar = AnalysisResult(
            investigation_id=inv.id,
            module_name="deepfake",
            score=None,
            result_data={"error": str(e), "status": "Unavailable — no reference/model", "method": "Unavailable"},
        )
        db.add(ar)
        db.commit()

def _run_identity_analysis(db: Session, inv: Investigation, frame_paths: list):
    """Run face identity comparison."""
    try:
        if not inv.identity_id:
            ar = AnalysisResult(
                investigation_id=inv.id,
                module_name="identity",
                score=None,
                result_data={"status": "No reference identity selected for comparison"},
            )
            db.add(ar)
            db.commit()
            return
        
        identity = db.query(Identity).filter(Identity.id == inv.identity_id).first()
        if not identity or not identity.face_embedding:
            ar = AnalysisResult(
                investigation_id=inv.id,
                module_name="identity",
                score=None,
                result_data={"status": "Reference identity has no face embedding"},
            )
            db.add(ar)
            db.commit()
            return
        
        from services.identity import generate_face_embedding, compare_faces, release_models
        
        similarities = []
        analysis_frames = []
        dimension_mismatch = False
        
        if inv.media_type == "image":
            emb = generate_face_embedding(inv.file_path)
            if emb:
                if len(emb) != len(identity.face_embedding):
                    dimension_mismatch = True
                sim = compare_faces(identity.face_embedding, emb)
                similarities.append(sim)
                analysis_frames.append({"path": inv.file_path, "similarity": sim})
        elif inv.media_type == "video" and frame_paths:
            for fp in frame_paths:
                emb = generate_face_embedding(fp)
                if emb:
                    if len(emb) != len(identity.face_embedding):
                        dimension_mismatch = True
                    sim = compare_faces(identity.face_embedding, emb)
                    similarities.append(sim)
                    analysis_frames.append({"path": fp, "similarity": sim})
        
        if similarities:
            best_sim = max(similarities)
            avg_sim = sum(similarities) / len(similarities)
            # If embeddings came from different model versions, flag mismatch
            mismatch_note = " Warning: reference embedding dimension mismatch (fallback 4096 vs FaceNet 512). Re-enroll the identity to refresh the embedding." if dimension_mismatch else ""
            ar = AnalysisResult(
                investigation_id=inv.id,
                module_name="identity",
                score=best_sim,
                confidence=avg_sim,
                result_data={
                    "best_similarity": best_sim,
                    "average_similarity": avg_sim,
                    "frames_analyzed": len(analysis_frames),
                    "frame_details": analysis_frames,
                    "reference_identity": identity.name,
                    "method": "Lightweight fallback" if len(identity.face_embedding) != 512 else "Face embedding model",
                    "model_status": "Advanced ML model unavailable on this machine" if len(identity.face_embedding) != 512 else "Advanced ML model available",
                    "status": ("Visual similarity signal (fallback)" if len(identity.face_embedding) != 512 else "Visual similarity signal") + mismatch_note,
                    "model_name": "FaceNet / InceptionResnetV1" if len(identity.face_embedding) == 512 else "Lightweight fallback",
                    "model_version": "pretrained VGGFace2" if len(identity.face_embedding) == 512 else "deterministic image embedding",
                    "timestamp": datetime.utcnow().isoformat(),
                    "note": "Cosine similarity score. Higher = more similar. This is a supporting signal, not proof of identity." + mismatch_note,
                    "dimension_mismatch": dimension_mismatch,
                },
            )
        else:
            ar = AnalysisResult(
                investigation_id=inv.id,
                module_name="identity",
                score=None,
                result_data={"status": "Unavailable — no detectable face", "method": "Unavailable"},
            )
        
        db.add(ar)
        db.commit()
        release_models()
    except Exception as e:
        print(f"Identity analysis error: {e}")
        ar = AnalysisResult(
            investigation_id=inv.id,
            module_name="identity",
            score=None,
            result_data={"error": str(e), "status": "Face identity module unavailable"},
        )
        db.add(ar)
        db.commit()

def _run_voice_analysis(db: Session, inv: Investigation):
    """Run voice/speaker verification."""
    try:
        if not inv.identity_id:
            ar = AnalysisResult(
                investigation_id=inv.id,
                module_name="voice",
                score=None,
                result_data={"status": "Voice comparison unavailable — no reference voice enrolled.", "method": "Unavailable"},
            )
            db.add(ar)
            db.commit()
            return
        
        identity = db.query(Identity).filter(Identity.id == inv.identity_id).first()
        if not identity or not identity.reference_audio_path:
            ar = AnalysisResult(
                investigation_id=inv.id,
                module_name="voice",
                score=None,
                result_data={"status": "Voice comparison unavailable — no reference voice enrolled.", "method": "Unavailable"},
            )
            db.add(ar)
            db.commit()
            return
        
        # Extract audio from video if needed
        audio_path = None
        if inv.media_type == "video":
            from services.voice import extract_audio
            audio_dir = os.path.join(EVIDENCE_DIR, "audio", str(inv.id))
            os.makedirs(audio_dir, exist_ok=True)
            audio_path = os.path.join(audio_dir, "extracted.wav")
            success = extract_audio(inv.file_path, audio_path)
            if not success:
                ar = AnalysisResult(
                    investigation_id=inv.id,
                    module_name="voice",
                    score=None,
                    result_data={"status": "Could not extract audio from video. Ensure ffmpeg is installed."},
                )
                db.add(ar)
                db.commit()
                return
        elif inv.media_type == "audio":
            audio_path = inv.file_path
        else:
            ar = AnalysisResult(
                investigation_id=inv.id,
                module_name="voice",
                score=None,
                result_data={"status": "Voice analysis not applicable for image media."},
            )
            db.add(ar)
            db.commit()
            return
        
        from services.voice import compare_voices, release_models
        voice_result = compare_voices(identity.reference_audio_path, audio_path)
        # compare_voices returns a dict with similarity_score, method, model_name, etc.
        similarity = voice_result.get("similarity_score") if isinstance(voice_result, dict) else voice_result
        # Normalize confidence: abs of similarity when numeric, else None
        try:
            conf = abs(float(similarity)) if similarity is not None else None
        except Exception:
            conf = None
        
        ar = AnalysisResult(
            investigation_id=inv.id,
            module_name="voice",
            score=float(similarity) if isinstance(similarity, (int, float)) and not isinstance(similarity, bool) else None,
            confidence=conf,
            result_data={
                **(voice_result if isinstance(voice_result, dict) else {"similarity_score": voice_result}),
                "similarity_score": similarity,
                "reference_identity": identity.name,
                "timestamp": datetime.utcnow().isoformat(),
                "note": "Speaker similarity score. This is supporting identity evidence, not proof of identity.",
            },
        )
        db.add(ar)
        db.commit()
        release_models()
    except Exception as e:
        print(f"Voice analysis error: {e}")
        ar = AnalysisResult(
            investigation_id=inv.id,
            module_name="voice",
            score=None,
            result_data={"error": str(e), "status": "Voice comparison unavailable — no reference voice enrolled.", "method": "Unavailable"},
        )
        db.add(ar)
        db.commit()

def _run_consistency_analysis(db: Session, inv: Investigation):
    """Run A/V consistency check."""
    try:
        from services.consistency import check_av_consistency
        result = check_av_consistency(inv.file_path)
        
        ar = AnalysisResult(
            investigation_id=inv.id,
            module_name="consistency",
            score=result.get("consistency_score"),
            result_data=result,
        )
        db.add(ar)
        db.commit()
        _add_timeline(db, inv.id, "av_consistency", "Audio-video consistency analysis completed")
    except Exception as e:
        print(f"Consistency analysis error: {e}")

def _run_similarity_search(db: Session, inv: Investigation):
    """Compare against previously indexed evidence using hashes."""
    try:
        matches = []
        
        # Get all evidence items with perceptual hashes from OTHER investigations
        all_evidence = db.query(Evidence).filter(
            Evidence.investigation_id != inv.id,
            Evidence.perceptual_hash.isnot(None)
        ).all()
        
        # Get current investigation's evidence
        current_evidence = db.query(Evidence).filter(
            Evidence.investigation_id == inv.id
        ).all()
        
        for curr_ev in current_evidence:
            if not curr_ev.sha256_hash and not curr_ev.perceptual_hash:
                continue
            for other_ev in all_evidence:
                # Check exact duplicate
                if curr_ev.sha256_hash and curr_ev.sha256_hash == other_ev.sha256_hash:
                    matches.append({
                        "type": "exact_duplicate",
                        "current_evidence_id": curr_ev.id,
                        "matched_evidence_id": other_ev.id,
                        "matched_investigation_id": other_ev.investigation_id,
                        "similarity": 1.0,
                    })
                elif curr_ev.perceptual_hash and other_ev.perceptual_hash:
                    # Compare perceptual hashes (hamming distance)
                    similarity = _compare_phash(curr_ev.perceptual_hash, other_ev.perceptual_hash)
                    if similarity > 0.8:
                        match_type = "near_duplicate" if similarity > 0.95 else "similar_frame"
                        matches.append({
                            "type": match_type,
                            "current_evidence_id": curr_ev.id,
                            "matched_evidence_id": other_ev.id,
                            "matched_investigation_id": other_ev.investigation_id,
                            "similarity": similarity,
                        })
        
        status = "No local match" if not matches else f"Found {len(matches)} similar items in indexed evidence"
        
        ar = AnalysisResult(
            investigation_id=inv.id,
            module_name="similarity",
            score=max((m["similarity"] for m in matches), default=0.0) if matches else 0.0,
            result_data={
                "matches": matches,
                "status": status,
                "note": "Similarity graph from indexed evidence. Does not represent the entire internet.",
            },
        )
        db.add(ar)
        db.commit()
    except Exception as e:
        print(f"Similarity search error: {e}")

def _run_provenance_analysis(db: Session, inv: Investigation):
    """Inspect uploaded media for independently verifiable C2PA credentials."""
    try:
        from services.provenance import inspect_c2pa

        result = inspect_c2pa(inv.file_path)
        ar = AnalysisResult(
            investigation_id=inv.id,
            module_name="provenance",
            score=None,
            result_data=result,
        )
        db.add(ar)
        db.commit()
        _add_timeline(db, inv.id, "provenance_check", "Provenance/C2PA status checked")
    except Exception as e:
        print(f"Provenance analysis error: {e}")

def _compare_phash(hash1: str, hash2: str) -> float:
    """Compare two hex-encoded perceptual hashes and return a similarity score 0-1."""
    try:
        h1 = int(hash1, 16)
        h2 = int(hash2, 16)
        xor = h1 ^ h2
        hamming = bin(xor).count('1')
        # 64-bit hash
        return 1.0 - (hamming / 64.0)
    except Exception:
        return 0.0

def _calculate_risk(db: Session, inv: Investigation):
    """
    Calculate a transparent risk score from available signals.
    Uses a documented weighted formula.
    """
    results = {ar.module_name: ar for ar in inv.analysis_results}
    
    contributors = {
        "voice": "UNAVAILABLE",
        "provenance": "UNAVAILABLE",
        "local_similarity": "NONE",
    }
    weighted_score = 0.0
    total_weight = 0.0
    
    # Manipulation signal (weight: 0.35)
    if "deepfake" in results and results["deepfake"].score is not None:
        w = 0.35
        s = results["deepfake"].score
        weighted_score += w * s
        total_weight += w
        contributors["manipulation_signal"] = _level(s)
    
    # Identity similarity (weight: 0.25)
    if "identity" in results and results["identity"].score is not None:
        w = 0.25
        s = results["identity"].score
        weighted_score += w * s
        total_weight += w
        contributors["visual_similarity"] = _level(s)
    
    # Voice similarity (weight: 0.15)
    if "voice" in results and results["voice"].score is not None:
        w = 0.15
        s = abs(results["voice"].score)
        weighted_score += w * s
        total_weight += w
        contributors["voice"] = _level(s)
    
    # AV consistency (weight: 0.10)
    if "consistency" in results and results["consistency"].score is not None:
        w = 0.10
        # Invert: high consistency = low risk
        s = 1.0 - results["consistency"].score
        weighted_score += w * s
        total_weight += w
        contributors["av_consistency"] = _level(results["consistency"].score)
    
    # Similarity/propagation (weight: 0.15)
    if "similarity" in results and results["similarity"].score is not None:
        w = 0.15
        s = results["similarity"].score
        weighted_score += w * s
        total_weight += w
        contributors["local_similarity"] = _level(s) if s else "NONE"
    
    if total_weight > 0:
        final_score = weighted_score / total_weight
    else:
        final_score = 0.0
    
    if final_score >= 0.75:
        risk_level = "CRITICAL"
    elif final_score >= 0.5:
        risk_level = "HIGH"
    elif final_score >= 0.25:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"
    
    inv.overall_risk_score = final_score
    inv.risk_level = risk_level
    
    # Store risk as an analysis result too
    ar = AnalysisResult(
        investigation_id=inv.id,
        module_name="risk_fusion",
        score=final_score,
        result_data={
            "risk_level": risk_level,
            "contributors": contributors,
            "formula": "Weighted average of available signals: manipulation(0.35) + visual_similarity(0.25) + voice(0.15) + av_consistency(0.10) + local_similarity(0.15). Unavailable signals are excluded.",
            "disclaimer": "Risk score is an analytical aid, not proof of manipulation or identity.",
        },
    )
    db.add(ar)
    db.commit()

def _level(score: float) -> str:
    if score >= 0.75:
        return "HIGH"
    elif score >= 0.5:
        return "MEDIUM"
    elif score >= 0.25:
        return "LOW"
    else:
        return "MINIMAL"

def _add_timeline(db: Session, investigation_id: int, event_type: str, description: str):
    event = TimelineEvent(
        investigation_id=investigation_id,
        event_type=event_type,
        description=description,
    )
    db.add(event)
    db.commit()

# ─── Timeline ─────────────────────────────────────────

@app.get("/api/investigation/{investigation_id}/timeline")
def get_timeline(investigation_id: int, db: Session = Depends(get_db)):
    events = db.query(TimelineEvent).filter(
        TimelineEvent.investigation_id == investigation_id
    ).order_by(TimelineEvent.created_at.asc()).all()
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "description": e.description,
            "created_at": str(e.created_at),
        }
        for e in events
    ]

# ─── Evidence ─────────────────────────────────────────

@app.get("/api/investigation/{investigation_id}/evidence")
def get_evidence(investigation_id: int, db: Session = Depends(get_db)):
    items = db.query(Evidence).filter(
        Evidence.investigation_id == investigation_id
    ).all()
    return [
        {
            "id": e.id,
            "type": e.evidence_type,
            "file_path": e.file_path,
            "sha256": e.sha256_hash,
            "perceptual_hash": e.perceptual_hash,
            "timestamp_offset": e.timestamp_offset,
        }
        for e in items
    ]

# ─── Similarity ───────────────────────────────────────

@app.get("/api/investigation/{investigation_id}/similarity")
def get_similarity(investigation_id: int, db: Session = Depends(get_db)):
    ar = db.query(AnalysisResult).filter(
        AnalysisResult.investigation_id == investigation_id,
        AnalysisResult.module_name == "similarity"
    ).first()
    if not ar:
        return {"status": "Similarity analysis not yet completed", "matches": []}
    return ar.result_data

# ─── Report ───────────────────────────────────────────

@app.get("/api/investigation/{investigation_id}/report")
def generate_report_endpoint(investigation_id: int, db: Session = Depends(get_db)):
    """Generate PDF forensic incident report."""
    try:
        from services.report import generate_report
        path = generate_report(investigation_id, db)
        if path:
            _add_timeline(db, investigation_id, "report_generated", "Forensic incident report generated")
            return {"report_path": path, "status": "generated"}
        raise HTTPException(status_code=404, detail="Investigation not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/report/{investigation_id}/download")
def download_report(investigation_id: int):
    """Download the generated PDF report."""
    path = os.path.join("data", "reports", f"DeepTrace_Report_INV{investigation_id}.pdf")
    if os.path.exists(path):
        return FileResponse(path, media_type="application/pdf", filename=f"DeepTrace_Report_INV{investigation_id}.pdf")
    raise HTTPException(status_code=404, detail="Report not found. Generate it first.")

# ─── Dashboard Stats ──────────────────────────────────

@app.get("/api/dashboard/stats")
def dashboard_stats(db: Session = Depends(get_db)):
    total_investigations = db.query(Investigation).count()
    total_evidence = db.query(Evidence).count()
    high_risk = db.query(Investigation).filter(Investigation.risk_level.in_(["HIGH", "CRITICAL"])).count()
    total_identities = db.query(Identity).count()
    
    return {
        "active_investigations": total_investigations,
        "evidence_items": total_evidence,
        "high_risk_findings": high_risk,
        "protected_identities": total_identities,
    }
