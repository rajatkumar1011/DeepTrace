import os
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from services.forensics import (
    audio_fingerprint,
    calculate_perceptual_hash,
    calculate_sha256,
    compare_audio_fingerprints,
)

MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 15
ALLOWED_SCHEMES = {"https"}


def parse_source_urls(raw) -> list:
    if raw is None:
        return []
    if isinstance(raw, list):
        values = raw
    else:
        text = str(raw).strip()
        if not text:
            return []
        if text.startswith("["):
            import json
            try:
                values = json.loads(text)
            except json.JSONDecodeError:
                values = [line.strip() for line in text.splitlines() if line.strip()]
        else:
            values = [line.strip() for line in text.replace(",", "\n").splitlines() if line.strip()]
    urls = []
    for item in values:
        url = str(item).strip()
        if url:
            urls.append(url)
    return urls[:8]


def validate_public_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return "Only https:// URLs are accepted."
    if not parsed.netloc:
        return "URL host is missing."
    host = parsed.hostname or ""
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
        return "Local addresses are not fetched."
    return None


def fetch_public_url(url: str, dest_dir: str):
    error = validate_public_url(url)
    if error:
        return {"url": url, "status": "rejected", "error": error}

    os.makedirs(dest_dir, exist_ok=True)
    ext = os.path.splitext(urlparse(url).path)[1] or ".bin"
    dest_path = os.path.join(dest_dir, f"{uuid4().hex}{ext[:8]}")
    request = Request(url, headers={"User-Agent": "DeepTrace/1.0 forensic-evidence-prototype"})
    try:
        with urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("Content-Type", "")
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_DOWNLOAD_BYTES:
                return {"url": url, "status": "rejected", "error": "Remote file exceeds 25 MB cap."}
            chunks = []
            total = 0
            while True:
                block = response.read(65536)
                if not block:
                    break
                total += len(block)
                if total > MAX_DOWNLOAD_BYTES:
                    return {"url": url, "status": "rejected", "error": "Download exceeded 25 MB cap."}
                chunks.append(block)
        with open(dest_path, "wb") as handle:
            handle.write(b"".join(chunks))
        return {
            "url": url,
            "status": "fetched",
            "file_path": dest_path,
            "bytes": total,
            "content_type": content_type,
        }
    except Exception as e:
        return {"url": url, "status": "failed", "error": str(e)}


def classify_copy(original_sha256, original_phash, original_audio_fp, copy_path, media_type: str):
    copy_sha = calculate_sha256(copy_path)
    copy_phash = None
    audio_sim = None
    if media_type in {"image", "video"}:
        copy_phash = calculate_perceptual_hash(copy_path)
    if media_type in {"audio", "video"}:
        copy_fp = audio_fingerprint(copy_path)
        audio_sim = compare_audio_fingerprints(original_audio_fp, copy_fp)

    match_type = "none"
    similarity = 0.0
    if original_sha256 and copy_sha == original_sha256:
        match_type = "exact"
        similarity = 1.0
    elif original_phash and copy_phash:
        try:
            h1 = int(original_phash, 16)
            h2 = int(copy_phash, 16)
            similarity = 1.0 - (bin(h1 ^ h2).count("1") / 64.0)
        except Exception:
            similarity = 0.0
        if similarity > 0.95:
            match_type = "near"
        elif similarity > 0.8:
            match_type = "similar"
    if match_type == "none" and audio_sim and audio_sim > 0.9:
        match_type = "near"
        similarity = max(similarity, audio_sim)

    return {
        "sha256": copy_sha,
        "perceptual_hash": copy_phash,
        "audio_fingerprint_similarity": audio_sim,
        "match_type": match_type,
        "similarity": similarity,
    }
