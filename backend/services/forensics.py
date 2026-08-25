"""Hashing, metadata extraction, frame sampling and perceptual fingerprinting.

Everything here is deterministic and model-free: these are the forensic
primitives the rest of the pipeline builds on.
"""

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone

import cv2
import numpy as np

# ffprobe/ffmpeg are looked up on PATH, or via FFMPEG_PATH for machines where the
# binaries live in a project-local folder.
_FFMPEG_HINT = os.environ.get("FFMPEG_PATH", "").strip()


def _binary(name: str) -> str:
    """Resolve ffmpeg/ffprobe without ever invoking a shell."""
    if _FFMPEG_HINT:
        candidate = os.path.join(_FFMPEG_HINT, f"{name}.exe" if os.name == "nt" else name)
        if os.path.isfile(candidate):
            return candidate
        if os.path.isfile(_FFMPEG_HINT) and os.path.basename(_FFMPEG_HINT).startswith(name):
            return _FFMPEG_HINT
    return shutil.which(name) or name


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None or bool(_FFMPEG_HINT)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ─── Integrity hashing ────────────────────────────────────────────────────────

def calculate_sha256(file_path: str) -> str | None:
    """SHA-256 of a file's exact bytes. Returns None if the file is unreadable."""
    digest = hashlib.sha256()
    try:
        with open(file_path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        print(f"SHA-256 unavailable for {file_path}: {error}")
        return None
    return digest.hexdigest()


def stream_to_disk(source, dest_path: str, max_bytes: int) -> tuple[int, str] | None:
    """Copy an upload to disk while hashing it, aborting past ``max_bytes``.

    Hashing during the write means the recorded digest belongs to the bytes that
    were actually persisted — a client-supplied hash is never trusted.
    Returns ``None`` (and removes the partial file) when the cap is exceeded.
    """
    digest = hashlib.sha256()
    total = 0
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    with open(dest_path, "wb") as handle:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                handle.close()
                try:
                    os.remove(dest_path)
                except OSError:
                    pass
                return None
            digest.update(chunk)
            handle.write(chunk)
    return total, digest.hexdigest()


def calculate_perceptual_hash(image_path: str) -> str | None:
    """64-bit pHash. Applies to still images and extracted video frames."""
    try:
        import imagehash
        from PIL import Image

        with Image.open(image_path) as img:
            return str(imagehash.phash(img))
    except Exception as error:
        print(f"Perceptual hash unavailable for {image_path}: {error}")
        return None


def phash_similarity(hash1: str | None, hash2: str | None) -> float:
    """1.0 - normalised Hamming distance between two hex pHashes."""
    if not hash1 or not hash2:
        return 0.0
    try:
        bits = max(len(hash1), len(hash2)) * 4
        distance = bin(int(hash1, 16) ^ int(hash2, 16)).count("1")
        return max(0.0, 1.0 - (distance / bits))
    except (ValueError, TypeError):
        return 0.0


def similarity_label(score: float) -> str:
    """Deliberately avoids the words 'copy' and 'identical' below an exact match."""
    if score >= 0.995:
        return "High similarity"
    if score >= 0.92:
        return "High similarity"
    if score >= 0.80:
        return "Moderate similarity"
    if score >= 0.65:
        return "Low similarity"
    return "Inconclusive"


# ─── Metadata / provenance signals ────────────────────────────────────────────

_MIME_MAP = {
    ".mp4": "video/mp4", ".avi": "video/x-msvideo", ".mov": "video/quicktime",
    ".mkv": "video/x-matroska", ".webm": "video/webm",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".bmp": "image/bmp", ".webp": "image/webp",
    ".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac",
    ".ogg": "audio/ogg", ".m4a": "audio/mp4",
}


def _guess_mime(path: str) -> str:
    return _MIME_MAP.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


def get_file_metadata(file_path: str) -> dict:
    stat = os.stat(file_path)
    return {
        "file_size_bytes": stat.st_size,
        "filesystem_created": datetime.fromtimestamp(stat.st_ctime, timezone.utc).isoformat(timespec="seconds"),
        "filesystem_modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
        "mime_type_by_extension": _guess_mime(file_path),
    }


def extract_image_metadata(file_path: str) -> dict | None:
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS

        with Image.open(file_path) as img:
            exif = {}
            raw = img.getexif()
            if raw:
                for tag_id, value in raw.items():
                    if isinstance(value, bytes):
                        continue
                    try:
                        exif[TAGS.get(tag_id, str(tag_id))] = str(value)[:200]
                    except Exception:
                        continue
            return {
                "width": img.width,
                "height": img.height,
                "resolution": f"{img.width}x{img.height}",
                "format": img.format,
                "mode": img.mode,
                "exif": exif,
                "exif_present": bool(exif),
            }
    except Exception as error:
        print(f"Image metadata error: {error}")
        return None


def probe_media(file_path: str) -> dict | None:
    """Raw ffprobe JSON, or None when FFmpeg is not installed."""
    try:
        result = subprocess.run(
            [
                _binary("ffprobe"), "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", file_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
            shell=False,
        )
        return json.loads(result.stdout or "{}")
    except Exception as error:
        print(f"ffprobe unavailable for {os.path.basename(file_path)}: {error}")
        return None


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def summarize_probe(probe: dict | None) -> dict:
    """Flatten the ffprobe payload into the provenance fields the report needs."""
    if not probe:
        return {}
    fmt = probe.get("format") or {}
    streams = probe.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    tags = fmt.get("tags") or {}

    frame_rate = None
    if video and video.get("avg_frame_rate") and "/" in str(video["avg_frame_rate"]):
        num, _, den = str(video["avg_frame_rate"]).partition("/")
        num_f, den_f = _as_float(num), _as_float(den)
        if num_f and den_f:
            frame_rate = round(num_f / den_f, 3)

    summary = {
        "container": fmt.get("format_name"),
        "container_long": fmt.get("format_long_name"),
        "duration_seconds": round(_as_float(fmt.get("duration")), 3) if _as_float(fmt.get("duration")) else None,
        "bitrate_bps": _as_int(fmt.get("bit_rate")),
        "stream_count": len(streams),
        "has_video": video is not None,
        "has_audio": audio is not None,
        "video_codec": (video or {}).get("codec_name"),
        "video_profile": (video or {}).get("profile"),
        "pixel_format": (video or {}).get("pix_fmt"),
        "video_duration_seconds": round(_as_float((video or {}).get("duration")), 3) if _as_float((video or {}).get("duration")) else None,
        "frame_rate": frame_rate,
        "nb_frames": _as_int((video or {}).get("nb_frames")),
        "audio_codec": (audio or {}).get("codec_name"),
        "audio_sample_rate": _as_int((audio or {}).get("sample_rate")),
        "audio_channels": _as_int((audio or {}).get("channels")),
        "audio_bitrate_bps": _as_int((audio or {}).get("bit_rate")),
        "audio_duration_seconds": round(_as_float((audio or {}).get("duration")), 3) if _as_float((audio or {}).get("duration")) else None,
        "width": _as_int((video or {}).get("width")),
        "height": _as_int((video or {}).get("height")),
        "encoder": tags.get("encoder") or tags.get("Encoder"),
        "creation_time": tags.get("creation_time"),
        "container_tags": {k: str(v)[:200] for k, v in tags.items()} or None,
    }
    if summary["width"] and summary["height"]:
        summary["resolution"] = f"{summary['width']}x{summary['height']}"
    return {k: v for k, v in summary.items() if v is not None}


def extract_video_metadata(file_path: str) -> dict | None:
    """ffprobe first, OpenCV as backfill. Does not write frames to disk."""
    probe = summarize_probe(probe_media(file_path))
    cap = cv2.VideoCapture(file_path)
    if not cap.isOpened():
        return probe or None

    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()

    opencv_duration = round(frame_count / fps, 3) if fps > 0 else None
    return {
        **probe,
        "duration_seconds": probe.get("duration_seconds") or opencv_duration,
        "resolution": probe.get("resolution") or (f"{width}x{height}" if width and height else None),
        "fps": probe.get("frame_rate") or (round(fps, 2) if fps else None),
        "frame_count": probe.get("nb_frames") or frame_count or None,
        "width": probe.get("width") or width or None,
        "height": probe.get("height") or height or None,
        "opencv_readable": True,
    }


def collect_media_metadata(file_path: str, media_type: str) -> dict:
    """Full provenance payload stored on the investigation and printed in the PDF."""
    payload = {
        "media_type": media_type,
        "extracted_at": utc_now_iso(),
        "ffprobe_available": ffmpeg_available(),
        "file": get_file_metadata(file_path),
    }
    probe = probe_media(file_path)
    if probe:
        payload["container"] = summarize_probe(probe)
        payload["streams"] = [
            {
                "index": stream.get("index"),
                "codec_type": stream.get("codec_type"),
                "codec_name": stream.get("codec_name"),
                "codec_long_name": stream.get("codec_long_name"),
                "duration_seconds": _as_float(stream.get("duration")),
                "width": _as_int(stream.get("width")),
                "height": _as_int(stream.get("height")),
                "sample_rate": _as_int(stream.get("sample_rate")),
                "channels": _as_int(stream.get("channels")),
            }
            for stream in (probe.get("streams") or [])
        ]
    else:
        payload["container"] = {}
        payload["note"] = (
            "FFprobe metadata unavailable — install FFmpeg to record container, "
            "codec and stream details."
        )

    if media_type == "image":
        image_meta = extract_image_metadata(file_path)
        if image_meta:
            payload["image"] = image_meta
    elif media_type == "video":
        video_meta = extract_video_metadata(file_path)
        if video_meta:
            payload["video"] = video_meta

    payload["interpretation"] = (
        "Metadata is a provenance signal only. Absent, generic or rewritten metadata "
        "is common in re-encoded and re-shared media and does not by itself indicate "
        "manipulation; present metadata does not establish authenticity."
    )
    return payload


# ─── Frame sampling ───────────────────────────────────────────────────────────

def extract_sampled_frames(file_path: str, dest_dir: str, num_samples: int = 12) -> list[dict]:
    """Evenly sample frames across the whole video.

    Sampling (rather than decoding every frame) keeps CPU-only analysis inside a
    demo-friendly time budget while still covering the full timeline.
    """
    os.makedirs(dest_dir, exist_ok=True)
    cap = cv2.VideoCapture(file_path)
    if not cap.isOpened():
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    frames: list[dict] = []
    if frame_count > 0:
        samples = max(1, min(num_samples, frame_count))
        # Sample at bin centres so the first frame is not always a black lead-in.
        indices = sorted({int((i + 0.5) * frame_count / samples) for i in range(samples)})
        for idx, frame_index in enumerate(indices):
            cap.set(cv2.CAP_PROP_POS_FRAMES, min(frame_index, max(frame_count - 1, 0)))
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            timestamp = frame_index / fps if fps > 0 else 0.0
            frame_path = os.path.join(dest_dir, f"frame_{idx:02d}_{timestamp:.2f}s.jpg")
            if cv2.imwrite(frame_path, frame):
                frames.append({"path": frame_path, "timestamp": round(timestamp, 3), "index": idx,
                               "frame_number": frame_index})
    else:
        # Streams with no reported frame count (some webm/fragmented mp4) still
        # decode sequentially, so fall back to reading forward.
        idx = 0
        while idx < num_samples:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            timestamp = (cap.get(cv2.CAP_PROP_POS_MSEC) or 0.0) / 1000.0
            frame_path = os.path.join(dest_dir, f"frame_{idx:02d}_{timestamp:.2f}s.jpg")
            if cv2.imwrite(frame_path, frame):
                frames.append({"path": frame_path, "timestamp": round(timestamp, 3), "index": idx,
                               "frame_number": None})
            idx += 1

    cap.release()
    return frames


def save_residual_overlay(image_path: str, dest_path: str) -> str | None:
    """High-frequency residual overlay used as a localization cue.

    This highlights where compression/blending artefacts concentrate in a frame.
    It is an explainable image-forensics visualisation, not a trained
    segmentation mask, and is labelled as such everywhere it is shown.
    """
    img = cv2.imread(image_path)
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    residual = cv2.absdiff(gray, cv2.GaussianBlur(gray, (5, 5), 0))
    residual = cv2.normalize(residual, None, 0, 255, cv2.NORM_MINMAX)
    heatmap = cv2.applyColorMap(residual.astype(np.uint8), cv2.COLORMAP_JET)
    overlay = cv2.addWeighted(img, 0.55, heatmap, 0.45, 0)
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    return dest_path if cv2.imwrite(dest_path, overlay) else None


# ─── Audio fingerprinting (for copy tracing, not speaker ID) ──────────────────

def load_audio_samples(file_path: str):
    """Mono float32 samples plus sample rate, via soundfile then scipy."""
    try:
        import soundfile as sf

        data, sample_rate = sf.read(file_path, always_2d=False)
    except Exception:
        try:
            from scipy.io import wavfile

            sample_rate, data = wavfile.read(file_path)
        except Exception as error:
            print(f"Audio load failed for {os.path.basename(file_path)}: {error}")
            return None, None

    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim > 1:
        arr = arr.mean(axis=1)
    if arr.size == 0:
        return None, None
    if np.issubdtype(np.asarray(data).dtype, np.integer):
        arr = arr / float(np.iinfo(np.asarray(data).dtype).max or 1)
    return arr, int(sample_rate)


def audio_fingerprint(file_path: str, bins: int = 32) -> list[float] | None:
    """Compact spectral fingerprint for copy similarity. Not speaker identification."""
    arr, sample_rate = load_audio_samples(file_path)
    if arr is None:
        return None
    peak = float(np.max(np.abs(arr))) or 1.0
    arr = arr / peak

    window = max(256, len(arr) // bins)
    features: list[float] = []
    for start in range(0, len(arr), window):
        chunk = arr[start:start + window]
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
    norm = float(np.linalg.norm(vec))
    return (vec / norm).tolist() if norm else None


def compare_audio_fingerprints(fp1, fp2) -> float:
    if not fp1 or not fp2:
        return 0.0
    a = np.array(fp1, dtype=np.float32)
    b = np.array(fp2, dtype=np.float32)
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    a, b = a[:n], b[:n]
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else 0.0
