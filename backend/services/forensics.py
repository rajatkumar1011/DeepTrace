import hashlib
import json
import os
import subprocess
from datetime import datetime

import cv2
import numpy as np


def calculate_sha256(file_path: str) -> str:
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def calculate_perceptual_hash(image_path: str):
    try:
        from PIL import Image
        import imagehash
        img = Image.open(image_path)
        return str(imagehash.phash(img))
    except Exception as e:
        print(f"Perceptual hash error: {e}")
        return None


def _guess_mime(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    mime_map = {
        ".mp4": "video/mp4", ".avi": "video/x-msvideo", ".mov": "video/quicktime",
        ".mkv": "video/x-matroska", ".webm": "video/webm",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".bmp": "image/bmp", ".webp": "image/webp",
        ".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac",
        ".ogg": "audio/ogg",
    }
    return mime_map.get(ext, "application/octet-stream")


def get_file_metadata(file_path: str):
    stat = os.stat(file_path)
    return {
        "file_size_bytes": stat.st_size,
        "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "mime_type": _guess_mime(file_path),
    }


def extract_image_metadata(file_path: str):
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS
        img = Image.open(file_path)
        exif = {}
        raw = img.getexif()
        if raw:
            for tag_id, value in raw.items():
                name = TAGS.get(tag_id, str(tag_id))
                if isinstance(value, bytes):
                    continue
                try:
                    exif[name] = str(value)[:200]
                except Exception:
                    continue
        return {
            "width": img.width,
            "height": img.height,
            "resolution": f"{img.width}x{img.height}",
            "format": img.format,
            "mode": img.mode,
            "exif": exif,
        }
    except Exception as e:
        print(f"Image metadata error: {e}")
        return None


def probe_media(file_path: str):
    """Return ffprobe JSON when FFmpeg is installed; otherwise None."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", file_path,
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        return json.loads(result.stdout or "{}")
    except Exception as e:
        print(f"ffprobe unavailable: {e}")
        return None


def summarize_probe(probe: dict):
    if not probe:
        return {}
    fmt = probe.get("format") or {}
    streams = probe.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = None
    try:
        duration = float(fmt.get("duration")) if fmt.get("duration") else None
    except (TypeError, ValueError):
        duration = None
    summary = {
        "container": fmt.get("format_name"),
        "duration_seconds": round(duration, 2) if duration is not None else None,
        "has_video": video is not None,
        "has_audio": audio is not None,
        "video_codec": (video or {}).get("codec_name"),
        "audio_codec": (audio or {}).get("codec_name"),
        "width": int(video["width"]) if video and video.get("width") else None,
        "height": int(video["height"]) if video and video.get("height") else None,
    }
    if video and video.get("width") and video.get("height"):
        summary["resolution"] = f"{video['width']}x{video['height']}"
    return summary


def extract_video_metadata(file_path: str):
    """OpenCV video properties only — does not write sampled frames."""
    probe = summarize_probe(probe_media(file_path))
    cap = cv2.VideoCapture(file_path)
    if not cap.isOpened():
        return probe or None

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps if fps > 0 else 0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    metadata = {
        "duration_seconds": probe.get("duration_seconds") or round(duration, 2),
        "resolution": probe.get("resolution") or f"{width}x{height}",
        "fps": round(fps, 2) if fps else None,
        "frame_count": frame_count,
        "width": probe.get("width") or width,
        "height": probe.get("height") or height,
        "has_audio": probe.get("has_audio"),
        "video_codec": probe.get("video_codec"),
        "audio_codec": probe.get("audio_codec"),
        "container": probe.get("container"),
        "frames_extracted": 0,
    }
    return metadata


def collect_media_metadata(file_path: str, media_type: str):
    payload = {"file": get_file_metadata(file_path), "media_type": media_type}
    probe = probe_media(file_path)
    if probe:
        payload["ffprobe"] = summarize_probe(probe)
    if media_type == "image":
        image_meta = extract_image_metadata(file_path)
        if image_meta:
            payload["image"] = image_meta
    elif media_type == "video":
        video_meta = extract_video_metadata(file_path)
        if video_meta:
            payload["video"] = video_meta
    elif media_type == "audio":
        payload["audio"] = payload.get("ffprobe") or {}
    return payload


def extract_sampled_frames(file_path: str, dest_dir: str, num_samples: int = 10):
    os.makedirs(dest_dir, exist_ok=True)
    cap = cv2.VideoCapture(file_path)
    if not cap.isOpened():
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    samples = min(num_samples, max(1, frame_count))
    intervals = [int(i * frame_count / samples) for i in range(samples)]

    frames = []
    for idx, frame_idx in enumerate(intervals):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            continue
        timestamp = frame_idx / fps if fps > 0 else 0.0
        frame_path = os.path.join(dest_dir, f"frame_{idx}_{timestamp:.2f}s.jpg")
        cv2.imwrite(frame_path, frame)
        frames.append({
            "path": frame_path,
            "timestamp": round(timestamp, 2),
            "index": idx,
        })
    cap.release()
    return frames


def save_residual_thumbnail(image_path: str, dest_path: str):
    """Cheap localization cue: high-frequency residual of a suspicious frame."""
    img = cv2.imread(image_path)
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    residual = cv2.absdiff(gray, blur)
    residual = cv2.normalize(residual, None, 0, 255, cv2.NORM_MINMAX)
    heatmap = cv2.applyColorMap(residual.astype(np.uint8), cv2.COLORMAP_JET)
    overlay = cv2.addWeighted(img, 0.55, heatmap, 0.45, 0)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    cv2.imwrite(dest_path, overlay)
    return dest_path


def audio_fingerprint(file_path: str, bins: int = 32):
    """Compact spectral fingerprint for local/URL similarity, not identification."""
    try:
        import soundfile as sf
        data, sample_rate = sf.read(file_path, always_2d=False)
    except Exception:
        try:
            from scipy.io import wavfile
            sample_rate, data = wavfile.read(file_path)
        except Exception as e:
            print(f"Audio fingerprint load error: {e}")
            return None

    if data is None:
        return None
    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim > 1:
        arr = arr.mean(axis=1)
    if arr.size == 0:
        return None
    peak = np.max(np.abs(arr)) or 1.0
    arr = arr / peak

    window = max(256, len(arr) // bins)
    features = []
    for i in range(0, len(arr), window):
        chunk = arr[i:i + window]
        if chunk.size == 0:
            continue
        spectrum = np.abs(np.fft.rfft(chunk))
        centroid = float(np.argmax(spectrum)) / max(len(spectrum) - 1, 1)
        features.extend([
            float(np.sqrt(np.mean(chunk ** 2))),
            float(np.std(chunk)),
            centroid,
        ])
        if len(features) >= bins * 3:
            break
    vec = np.array(features[: bins * 3], dtype=np.float32)
    if vec.size == 0:
        return None
    norm = np.linalg.norm(vec)
    if norm == 0:
        return None
    return (vec / norm).tolist()


def compare_audio_fingerprints(fp1, fp2) -> float:
    if not fp1 or not fp2:
        return 0.0
    a = np.array(fp1, dtype=np.float32)
    b = np.array(fp2, dtype=np.float32)
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    a, b = a[:n], b[:n]
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)
