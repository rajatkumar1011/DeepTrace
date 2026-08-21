import os
import tempfile

import cv2
import numpy as np


def _load_face_cascade():
    cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
    cascade = cv2.CascadeClassifier(cascade_path)
    if cascade.empty():
        return None
    return cascade


def _audio_has_energy(audio_path: str, timestamps, window_seconds: float = 0.4):
    try:
        import soundfile as sf
        data, sample_rate = sf.read(audio_path, always_2d=False)
    except Exception:
        try:
            from scipy.io import wavfile
            sample_rate, data = wavfile.read(audio_path)
        except Exception as e:
            return None, str(e)

    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim > 1:
        arr = arr.mean(axis=1)
    if arr.size == 0:
        return [], "empty audio"
    peak = np.max(np.abs(arr)) or 1.0
    arr = arr / peak
    half = int((window_seconds / 2.0) * sample_rate)
    energies = []
    for ts in timestamps:
        center = int(ts * sample_rate)
        start = max(0, center - half)
        end = min(len(arr), center + half)
        chunk = arr[start:end]
        rms = float(np.sqrt(np.mean(chunk ** 2))) if chunk.size else 0.0
        energies.append(rms)
    return energies, None


def check_av_consistency(video_path: str, frame_items: list = None, audio_path: str = None) -> dict:
    """
    Lightweight A/V heuristic: face presence on sampled frames vs audio energy
    at the same timestamps. This is not SyncNet or deep multimodal verification.
    """
    frame_items = frame_items or []
    probe_error = None
    audio_present = os.path.isfile(audio_path) if audio_path else False

    if not audio_present:
        from services.voice import extract_audio
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        audio_present = extract_audio(video_path, tmp.name)
        audio_path = tmp.name if audio_present else None
        if not audio_present:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            return {
                "status": "unavailable",
                "consistency_score": None,
                "audio_present": False,
                "face_present_ratio": None,
                "energy_alignment_score": None,
                "method": "Face presence vs audio RMS windows",
                "model_status": "Heuristic only; no audio stream extracted",
                "details": "No extractable audio stream. A/V consistency was excluded from risk fusion.",
            }

    cascade = _load_face_cascade()
    timestamps = []
    face_flags = []
    for item in frame_items:
        path = item.get("path") if isinstance(item, dict) else item
        ts = item.get("timestamp", 0.0) if isinstance(item, dict) else 0.0
        timestamps.append(float(ts))
        img = cv2.imread(path) if path else None
        has_face = False
        if img is not None and cascade is not None:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=4, minSize=(40, 40))
            has_face = len(faces) > 0
        face_flags.append(has_face)

    if not timestamps:
        return {
            "status": "unavailable",
            "consistency_score": None,
            "audio_present": True,
            "face_present_ratio": None,
            "energy_alignment_score": None,
            "method": "Face presence vs audio RMS windows",
            "model_status": "Heuristic only",
            "details": "No sampled frames were available for alignment.",
        }

    energies, energy_error = _audio_has_energy(audio_path, timestamps)
    if energy_error or energies is None:
        return {
            "status": "unavailable",
            "consistency_score": None,
            "audio_present": True,
            "face_present_ratio": None,
            "energy_alignment_score": None,
            "method": "Face presence vs audio RMS windows",
            "model_status": "Heuristic only",
            "details": f"Audio energy could not be measured: {energy_error}",
        }

    energy_threshold = max(0.02, float(np.median(energies)) * 0.5)
    face_ratio = sum(1 for flag in face_flags if flag) / len(face_flags)
    aligned = 0
    compared = 0
    for face, energy in zip(face_flags, energies):
        compared += 1
        speaking = energy >= energy_threshold
        if face == speaking:
            aligned += 1
    alignment = aligned / compared if compared else None

    return {
        "status": "completed",
        "consistency_score": alignment,
        "audio_present": True,
        "face_present_ratio": face_ratio,
        "energy_alignment_score": alignment,
        "energy_threshold": energy_threshold,
        "samples_compared": compared,
        "method": "Face presence vs audio RMS windows",
        "model_status": "Lightweight heuristic (not SyncNet)",
        "details": "Alignment is the share of sampled timestamps where face presence and audio energy agree. Prototype heuristic, not deep lip-sync verification.",
        "warning": "This is a supporting forensic signal, not proof of manipulation.",
    }
