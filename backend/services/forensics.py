import os
import hashlib
import cv2
import json
from datetime import datetime

def calculate_sha256(file_path: str) -> str:
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def calculate_perceptual_hash(image_path: str) -> str:
    """Calculate perceptual hash of an image using imagehash."""
    try:
        from PIL import Image
        import imagehash
        img = Image.open(image_path)
        return str(imagehash.phash(img))
    except Exception as e:
        print(f"Perceptual hash error: {e}")
        return None

def extract_video_metadata(file_path: str):
    """Extracts basic video metadata using OpenCV."""
    cap = cv2.VideoCapture(file_path)
    if not cap.isOpened():
        return None
    
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps if fps > 0 else 0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    # Extract sampled frames
    extracted_frames_count = 0
    if frame_count > 0:
        frames_dir = os.path.join("evidence", "frames")
        os.makedirs(frames_dir, exist_ok=True)
        
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        
        num_samples = min(10, max(1, frame_count))
        intervals = [int(i * frame_count / num_samples) for i in range(num_samples)]
        
        for idx, frame_idx in enumerate(intervals):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if ret:
                frame_path = os.path.join(frames_dir, f"{base_name}_frame_{idx}.jpg")
                cv2.imwrite(frame_path, frame)
                extracted_frames_count += 1
                
    cap.release()
    
    return {
        "duration_seconds": round(duration, 2),
        "resolution": f"{width}x{height}",
        "fps": round(fps, 2),
        "frames_extracted": extracted_frames_count,
        "frame_count": frame_count,
        "width": width,
        "height": height,
    }

def extract_image_metadata(file_path: str):
    """Extract metadata from an image file."""
    try:
        from PIL import Image
        img = Image.open(file_path)
        return {
            "width": img.width,
            "height": img.height,
            "resolution": f"{img.width}x{img.height}",
            "format": img.format,
            "mode": img.mode,
        }
    except Exception as e:
        print(f"Image metadata error: {e}")
        return None

def get_file_metadata(file_path: str):
    """Get general file metadata."""
    stat = os.stat(file_path)
    return {
        "file_size_bytes": stat.st_size,
        "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "mime_type": _guess_mime(file_path),
    }

def _guess_mime(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    mime_map = {
        '.mp4': 'video/mp4', '.avi': 'video/x-msvideo', '.mov': 'video/quicktime',
        '.mkv': 'video/x-matroska', '.webm': 'video/webm',
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
        '.bmp': 'image/bmp', '.webp': 'image/webp',
        '.wav': 'audio/wav', '.mp3': 'audio/mpeg', '.flac': 'audio/flac',
    }
    return mime_map.get(ext, 'application/octet-stream')
