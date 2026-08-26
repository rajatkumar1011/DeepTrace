"""External provenance estimation: reverse-image discovery, then local verification.

Two stages, deliberately separate, because they establish different things:

1. **Discovery** — sampled frames are sent to Google Lens through SerpApi, which
   answers with pages that carry visually similar imagery. Discovery alone
   establishes *nothing*: Lens is a similarity index, and a returned URL is a
   lead, not a finding.
2. **Verification** — DeepTrace fetches each candidate page itself, pulls the
   media it actually serves, and compares that media against the media under
   investigation using perceptual hashes plus, where a face is present in both,
   the same FaceNet embedding the identity module already uses. Only a candidate
   that survives this local comparison is reported as a provenance candidate.

What this is *not*:

* It is not an internet-wide search. It queries one third-party index through a
  documented, authenticated API and fetches only the URLs that index returned.
* It does not access private or authenticated endpoints, and it bypasses no
  access control. Every URL is put through the same SSRF validation used by
  manual copy tracing, and anything private, loopback or non-HTTPS is refused.
* "Earliest observed" is not "original". An archive capture proves a URL held
  certain bytes at a certain time; absence of a capture proves nothing at all.
* The confidence figure is an engineering score for ranking leads, not a
  calibrated probability.

Configuration: ``SERPAPI_API_KEY`` in the environment or in ``backend/.env``
(gitignored). Absent a key, ``estimate`` reports ``not_configured`` and the
pipeline records that truthfully rather than inventing sources.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import cv2
import imagehash
import numpy as np
import requests
from PIL import Image, ImageOps

from services.tracing import validate_public_url

SERPAPI_IMAGE_ENDPOINT = "https://serpapi.com/image"
SERPAPI_SEARCH_ENDPOINT = "https://serpapi.com/search.json"

# Discovery sampling is deliberately sparse. Consecutive frames of a talking-head
# clip return near-identical Lens results, so a dense sample spends quota and
# wall-clock for almost no extra recall. Dense sampling happens later, locally,
# during verification where it costs nothing but CPU.
DISCOVERY_FRAME_INTERVAL = 3.0
DISCOVERY_MAX_FRAMES = 4
MAX_SOURCES = 10
VERIFY_MAX_SOURCES = 6

# Verification sampling: the reference signature the candidates are compared to.
VERIFY_FRAME_INTERVAL = 2.0
VERIFY_MAX_FRAMES = 8
MAX_IMAGES_PER_PAGE = 8

MEDIA_THRESHOLD = 0.78          # combined perceptual-hash similarity
FACE_THRESHOLD = 0.60           # cosine similarity, InceptionResnetV1 / VGGFace2
FACE_SUPPORT_MIN_MEDIA = 0.45   # below this, a face check cannot rescue the match
VIDEO_FRAME_THRESHOLD = 0.78
VIDEO_FRAME_MATCH_RATIO = 0.30
FACE_MATCH_RATIO = 0.25

REQUEST_TIMEOUT = 30
LENS_TIMEOUT = 60
LENS_MAX_RETRIES = 1
LENS_RETRY_BACKOFF = 2.0
MAX_LENS_WORKERS = 4
MAX_CRAWL_WORKERS = 3
MAX_PAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_VIDEO_BYTES = 200 * 1024 * 1024
YTDLP_METADATA_TIMEOUT = 30
YTDLP_VIDEO_TIMEOUT = 120

# Downloading a full candidate video costs up to two minutes per source, which is
# not something to spend inside a synchronous analysis run by default. Thumbnail
# and page-image verification stays on; whole-video acquisition is opt-in, and the
# payload says which of the two actually ran so the reader is never misled about
# the depth of the check.
FETCH_CANDIDATE_VIDEO = (os.environ.get("DEEPTRACE_PROVENANCE_FETCH_VIDEO", "").strip().lower()
                         in {"1", "true", "yes", "on"})

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT}

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "igshid", "igsh", "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src",
    "spm", "si", "feature",
}

SOCIAL_PLATFORMS = {"YouTube", "Instagram", "Facebook", "X"}

LIMITATIONS = [
    "Discovery is a reverse-image similarity lookup through one third-party index (Google Lens via SerpApi). It is not an internet-wide search and its recall is unknown.",
    "The earliest observed source is not guaranteed to be the original source or the first upload.",
    "Absence from a web archive is not evidence that a source never existed.",
    "Many social pages render client-side or refuse automated retrieval, so an unverified source is not a cleared source.",
    "A thumbnail match is not treated as a match of the video itself.",
    "Confidence is an engineering score for ranking leads, not a calibrated probability.",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ── Configuration ────────────────────────────────────────────────────────────

def _read_dotenv_key(name: str) -> str:
    """Read one key from backend/.env.

    The repository carries no secrets, so the key lives in a gitignored file next
    to the backend. Parsed here rather than through python-dotenv to avoid adding
    a dependency for six lines of work.
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                if key.strip() == name:
                    return value.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def api_key() -> str:
    return (os.environ.get("SERPAPI_API_KEY", "").strip() or _read_dotenv_key("SERPAPI_API_KEY"))


def is_configured() -> bool:
    return bool(api_key())


# ── URL handling ─────────────────────────────────────────────────────────────

def normalize_url(url: str | None) -> str | None:
    """Canonicalise a URL so one post shared through different tracked links is
    not counted as several distinct sources."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return None
        query = ""
        if parsed.query:
            query = "&".join(
                pair for pair in parsed.query.split("&")
                if pair.split("=")[0].lower() not in TRACKING_PARAMS
            )
        path = parsed.path
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/")
        return parsed._replace(path=path, query=query, fragment="").geturl()
    except ValueError:
        return None


def platform_for(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "youtube.com" in host or "youtu.be" in host:
        return "YouTube"
    if "instagram.com" in host:
        return "Instagram"
    if "facebook.com" in host or "fb.watch" in host:
        return "Facebook"
    if "x.com" in host or "twitter.com" in host:
        return "X"
    return "Web"


def _fetchable(url: str) -> str | None:
    """The same SSRF gate manual copy tracing uses.

    A URL arriving from a third-party index is no more trusted than one typed by
    a user: it is still an instruction to make DeepTrace's server issue a request
    to an address chosen by someone else.
    """
    return validate_public_url(url)


# ── Frame sampling ───────────────────────────────────────────────────────────

def _sample_video_frames(path: str, interval: float, limit: int) -> list[dict]:
    capture = cv2.VideoCapture(path)
    if not capture.isOpened():
        raise RuntimeError("OpenCV could not open the media for frame sampling.")
    try:
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        total = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        duration = (total / fps) if fps else 0.0

        frames: list[dict] = []
        position = 0.0
        while position <= duration and len(frames) < limit:
            capture.set(cv2.CAP_PROP_POS_MSEC, position * 1000)
            ok, frame = capture.read()
            if not ok:
                break
            frames.append({
                "index": len(frames) + 1,
                "timestamp": round(position, 3),
                "image": Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGB"),
            })
            position += interval
        return frames
    finally:
        capture.release()


def _sample_frames(file_path: str, media_type: str, interval: float, limit: int) -> list[dict]:
    """Sample the media into comparable still images.

    A still image is its own single sample; treating it as a one-frame video keeps
    every downstream comparison identical for both media types.
    """
    if media_type == "image":
        image = _load_image_file(file_path)
        if image is None:
            raise RuntimeError("The image could not be decoded for comparison.")
        return [{"index": 1, "timestamp": 0.0, "image": image}]
    return _sample_video_frames(file_path, interval, limit)


def _load_image_file(path: str):
    try:
        with open(path, "rb") as handle:
            return _load_image_bytes(handle.read())
    except OSError:
        return None


def _load_image_bytes(data: bytes):
    """Decode candidate bytes defensively — a page can serve anything."""
    try:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image)
        image.load()
        if image.mode in ("P", "LA", "RGBA"):
            rgba = image.convert("RGBA")
            flattened = Image.new("RGB", rgba.size, "white")
            flattened.paste(rgba, mask=rgba.getchannel("A"))
            return flattened
        return image.convert("RGB")
    except Exception:
        return None


def _encode_jpeg(image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


# ── Perceptual comparison ────────────────────────────────────────────────────

def _hashes(image) -> dict:
    scaled = image.copy()
    scaled.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    return {
        "phash": imagehash.phash(scaled),
        "dhash": imagehash.dhash(scaled),
        "ahash": imagehash.average_hash(scaled),
    }


def _hash_similarity(left, right) -> float:
    return max(0.0, min(1.0, 1.0 - ((left - right) / 64.0)))


def _compare_hashes(left: dict, right: dict) -> dict:
    phash = _hash_similarity(left["phash"], right["phash"])
    dhash = _hash_similarity(left["dhash"], right["dhash"])
    ahash = _hash_similarity(left["ahash"], right["ahash"])
    return {
        "phash_distance": int(left["phash"] - right["phash"]),
        "dhash_distance": int(left["dhash"] - right["dhash"]),
        "ahash_distance": int(left["ahash"] - right["ahash"]),
        "phash_similarity": round(phash, 4),
        "dhash_similarity": round(dhash, 4),
        "ahash_similarity": round(ahash, 4),
        "combined_score": round(0.50 * phash + 0.30 * dhash + 0.20 * ahash, 4),
    }


def _face_embedding(image):
    """Embed the largest detected face with the project's existing FaceNet stack.

    Reused rather than reimplemented: the identity module already loads MTCNN and
    InceptionResnetV1, already publishes its threshold, and a second face library
    with a second threshold would mean two different definitions of "same person"
    inside one report. Returns ``None`` when no face is detected, which is a
    finding in itself and not an error.
    """
    from services import identity

    handle, temp_path = tempfile.mkstemp(suffix=".jpg", prefix="deeptrace_prov_")
    os.close(handle)
    try:
        image.copy().save(temp_path, format="JPEG", quality=92)
        if identity.get_models()[0] is None:
            # Without a detector, the identity module falls back to a centre crop,
            # which is not face recognition. Declining is the honest answer.
            return None
        return identity.generate_face_embedding(temp_path)
    except Exception:
        return None
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def _compare_faces(reference_embeddings: list, candidate_embedding) -> dict:
    from services import identity

    if not reference_embeddings:
        return {"status": "NO_REFERENCE_FACE", "similarity": None}
    if not candidate_embedding:
        return {"status": "NO_CANDIDATE_FACE", "similarity": None}

    best = max(identity.compare_faces(reference, candidate_embedding)
               for reference in reference_embeddings)
    return {
        "status": "FACE_MATCH" if best >= FACE_THRESHOLD else "FACE_NOT_MATCHED",
        "similarity": round(float(best), 4),
        "threshold": FACE_THRESHOLD,
        "model": identity.active_model_name(),
    }


def _combine(media: dict, face: dict) -> float:
    """Fold face support into the media score only when a face exists on both sides."""
    score = media["combined_score"]
    if face["status"] in ("FACE_MATCH", "FACE_NOT_MATCHED") and face["similarity"] is not None:
        score = 0.60 * score + 0.40 * max(0.0, face["similarity"])
    return round(score, 4)


def build_reference_signature(file_path: str, media_type: str) -> dict:
    """Hash (and where possible face-embed) the media under investigation."""
    frames = _sample_frames(file_path, media_type, VERIFY_FRAME_INTERVAL, VERIFY_MAX_FRAMES)
    entries = []
    embeddings = []
    for frame in frames:
        embedding = _face_embedding(frame["image"])
        if embedding:
            embeddings.append(embedding)
        entries.append({
            "frame": frame["index"],
            "timestamp": frame["timestamp"],
            "hashes": _hashes(frame["image"]),
        })
    return {
        "frames": entries,
        "face_embeddings": embeddings,
        "frames_sampled": len(entries),
        "frames_with_face": len(embeddings),
    }


def _compare_candidate_image(reference: dict, image) -> dict | None:
    """Best hash match of one candidate image against every reference frame."""
    candidate_hashes = _hashes(image)
    best = None
    for entry in reference["frames"]:
        media = _compare_hashes(entry["hashes"], candidate_hashes)
        if best is None or media["combined_score"] > best["media"]["combined_score"]:
            best = {
                "reference_frame": entry["frame"],
                "reference_timestamp": entry["timestamp"],
                "media": media,
            }
    if best is None:
        return None

    # Face embedding is the expensive half, so it only runs where it can change
    # the outcome. Below FACE_SUPPORT_MIN_MEDIA the images are not the same frame
    # and a facial resemblance would not make them one.
    face = {"status": "NOT_CHECKED", "similarity": None}
    if best["media"]["combined_score"] >= FACE_SUPPORT_MIN_MEDIA and reference["face_embeddings"]:
        face = _compare_faces(reference["face_embeddings"], _face_embedding(image))
    best["face"] = face
    best["combined_score"] = _combine(best["media"], face)
    return best


# ── Discovery: Google Lens via SerpApi ───────────────────────────────────────

def _lens_once(jpeg: bytes, key: str) -> dict:
    upload = requests.post(
        SERPAPI_IMAGE_ENDPOINT,
        files={"image": ("frame.jpg", jpeg, "image/jpeg")},
        data={"api_key": key},
        headers=HEADERS,
        timeout=LENS_TIMEOUT,
    )
    upload.raise_for_status()
    uploaded = upload.json()
    if uploaded.get("error"):
        raise RuntimeError(str(uploaded["error"]))
    image_id = uploaded.get("image_id")
    if not image_id:
        raise RuntimeError("SerpApi accepted the upload but returned no image_id.")

    search = requests.get(
        SERPAPI_SEARCH_ENDPOINT,
        params={"engine": "google_lens", "image_id": image_id, "api_key": key, "type": "all"},
        headers=HEADERS,
        timeout=LENS_TIMEOUT,
    )
    search.raise_for_status()
    result = search.json()
    if result.get("error"):
        raise RuntimeError(str(result["error"]))
    return result


def _lens_search(jpeg: bytes, key: str) -> dict:
    """One flaky call must not lose a frame, so retry once with backoff."""
    last_error: Exception | None = None
    for attempt in range(1, LENS_MAX_RETRIES + 2):
        try:
            return _lens_once(jpeg, key)
        except Exception as error:
            last_error = error
            if attempt <= LENS_MAX_RETRIES:
                time.sleep(LENS_RETRY_BACKOFF * attempt)
    raise last_error if last_error else RuntimeError("Lens search failed.")


def _extract_lens_sources(response: dict) -> list[dict]:
    found = []
    for key in ("visual_matches", "image_results"):
        for item in response.get(key, []) or []:
            url = normalize_url(item.get("link") or item.get("source"))
            if not url:
                continue
            found.append({
                "url": url,
                "title": item.get("title"),
                "publisher": item.get("source"),
                "thumbnail": item.get("thumbnail"),
                "match_type": key,
            })
    return found


def _rank(source: dict) -> int:
    """Rank leads by how often they recurred and how likely they carry the media.

    Recurrence across independently sampled frames is the strongest cheap signal
    that a page holds this clip rather than one lookalike still.
    """
    url = source["url"].lower()
    score = source["frame_occurrence_count"] * 10
    if any(token in url for token in ("youtube.com", "youtu.be", "facebook.com",
                                      "instagram.com", "x.com", "twitter.com")):
        score += 4
    if any(token in url for token in ("/video", "/videos", "/watch", "/reel", ".mp4")):
        score += 3
    if source.get("publisher"):
        score += 1
    return score


def _union(frame_results: list[dict]) -> list[dict]:
    by_url: dict[str, dict] = {}
    for item in frame_results:
        for found in item["sources"]:
            entry = by_url.setdefault(found["url"], {
                "url": found["url"],
                "title": found.get("title"),
                "publisher": found.get("publisher"),
                "thumbnail": found.get("thumbnail"),
                "found_by_frames": [],
                "found_at_timestamps": [],
            })
            if item["frame"] not in entry["found_by_frames"]:
                entry["found_by_frames"].append(item["frame"])
                entry["found_at_timestamps"].append(item["timestamp"])
            entry.setdefault("title", found.get("title"))

    sources = list(by_url.values())
    for source in sources:
        source["frame_occurrence_count"] = len(source["found_by_frames"])
        source["rank_score"] = _rank(source)
        source["platform"] = platform_for(source["url"])
    sources.sort(key=lambda item: (item["rank_score"], item["frame_occurrence_count"]), reverse=True)
    return sources


def discover(file_path: str, media_type: str) -> dict:
    """Reverse-image lookup over sampled frames. Returns leads, never findings."""
    key = api_key()
    if not key:
        return {
            "status": "not_configured",
            "reason": "No SerpApi key is configured, so no reverse-image discovery was attempted.",
            "sources": [],
        }

    try:
        frames = _sample_frames(file_path, media_type, DISCOVERY_FRAME_INTERVAL, DISCOVERY_MAX_FRAMES)
    except Exception as error:
        return {"status": "failed", "reason": f"Frame sampling failed: {error}", "sources": []}
    if not frames:
        return {"status": "failed", "reason": "No frames could be sampled from this media.", "sources": []}

    queries = []
    for frame in frames:
        jpeg = _encode_jpeg(frame["image"])
        queries.append({
            "frame": frame["index"],
            "timestamp": frame["timestamp"],
            "jpeg": jpeg,
            "sha256": _sha256_bytes(jpeg),
        })

    def _one(query: dict) -> dict:
        try:
            sources = _extract_lens_sources(_lens_search(query["jpeg"], key))
            return {"frame": query["frame"], "timestamp": query["timestamp"],
                    "sha256": query["sha256"], "sources": sources, "error": None}
        except Exception as error:
            return {"frame": query["frame"], "timestamp": query["timestamp"],
                    "sha256": query["sha256"], "sources": [], "error": str(error)}

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=MAX_LENS_WORKERS) as pool:
        futures = [pool.submit(_one, query) for query in queries]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: item["frame"])

    sources = _union(results)
    errors = [item["error"] for item in results if item["error"]]
    searched = [item for item in results if not item["error"]]

    if not searched:
        return {
            "status": "failed",
            "reason": f"Every reverse-image query failed. First error: {errors[0]}" if errors
                      else "Every reverse-image query failed.",
            "sources": [],
            "queries": [{k: v for k, v in item.items() if k != "jpeg"} for item in results],
        }

    return {
        "status": "completed",
        # The query frames are hashed and listed so the discovery step is
        # reproducible: an auditor can see exactly which images were sent out.
        "queries": [
            {"frame": item["frame"], "timestamp": item["timestamp"],
             "query_image_sha256": item["sha256"], "sources_returned": len(item["sources"]),
             "error": item["error"]}
            for item in results
        ],
        "frames_searched": len(searched),
        "frames_failed": len(errors),
        "raw_match_count": sum(len(item["sources"]) for item in results),
        "unique_source_count": len(sources),
        "sources": sources[:MAX_SOURCES],
        "engine": "Google Lens via SerpApi",
        "method": (f"{len(searched)} frame(s) sampled at {DISCOVERY_FRAME_INTERVAL}s intervals and "
                   "submitted to Google Lens through SerpApi; results de-duplicated and ranked by "
                   "cross-frame recurrence."),
    }


# ── Verification: fetch the candidate and compare it locally ─────────────────

def _fetch_page(url: str) -> tuple[str, int, bytes]:
    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT,
                            allow_redirects=True, stream=True)
    response.raise_for_status()
    body = bytearray()
    for chunk in response.iter_content(64 * 1024):
        body.extend(chunk)
        if len(body) > MAX_PAGE_BYTES:
            raise RuntimeError("Page exceeded the size limit.")
    return response.url, response.status_code, bytes(body)


def _extract_page_media(page_url: str, html: str) -> dict:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    images: list[str] = []
    videos: list[str] = []

    for prop in ("og:image", "og:image:url", "og:image:secure_url"):
        tag = soup.find("meta", property=prop)
        if tag and tag.get("content"):
            images.append(urljoin(page_url, tag["content"]))
    for prop in ("og:video", "og:video:url", "og:video:secure_url"):
        tag = soup.find("meta", property=prop)
        if tag and tag.get("content"):
            videos.append(urljoin(page_url, tag["content"]))
    for name in ("twitter:image", "twitter:image:src"):
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            images.append(urljoin(page_url, tag["content"]))

    for img in soup.find_all("img"):
        for attr in ("src", "data-src", "data-original", "data-lazy-src"):
            if img.get(attr):
                images.append(urljoin(page_url, img[attr]))
                break
        if img.get("srcset"):
            images += [urljoin(page_url, part.strip().split()[0])
                       for part in img["srcset"].split(",") if part.strip()]

    for video in soup.find_all("video"):
        if video.get("src"):
            videos.append(urljoin(page_url, video["src"]))
        if video.get("poster"):
            images.append(urljoin(page_url, video["poster"]))
        for source in video.find_all("source"):
            if source.get("src"):
                videos.append(urljoin(page_url, source["src"]))

    def clean(items: list[str], limit: int) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for item in items:
            normalized = normalize_url(item)
            if normalized and normalized not in seen:
                seen.add(normalized)
                out.append(normalized)
        return out[:limit]

    return {"images": clean(images, MAX_IMAGES_PER_PAGE), "videos": clean(videos, 4)}


def _extract_published_at(html: str) -> str | None:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    values: list[str] = []
    for attrs in ({"property": "article:published_time"}, {"property": "og:published_time"},
                  {"name": "date"}, {"name": "pubdate"}, {"name": "publish_date"},
                  {"itemprop": "datePublished"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            values.append(tag["content"].strip())

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                for field in ("datePublished", "uploadDate", "dateCreated"):
                    if item.get(field):
                        values.append(str(item[field]))
                stack.extend(value for value in item.values() if isinstance(value, (dict, list)))
            elif isinstance(item, list):
                stack.extend(item)
    return next((value for value in values if value), None)


def _wayback_first_observed(url: str) -> dict | None:
    """Earliest archived capture of this URL, if any.

    A capture is evidence that the URL served a 200 at that time. It is not
    evidence of authorship, and its absence is not evidence of anything.
    """
    try:
        response = requests.get(
            "https://web.archive.org/cdx/search/cdx",
            params={"url": url, "output": "json", "filter": "statuscode:200",
                    "fl": "timestamp,original,statuscode,digest", "limit": 1,
                    "from": "1990", "to": "2999"},
            headers=HEADERS, timeout=REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            return None
        rows = response.json()
        if len(rows) >= 2:
            row = rows[1]
            return {"timestamp": row[0], "original": row[1],
                    "statuscode": row[2], "digest": row[3]}
    except Exception:
        pass
    return None


def _download_image(url: str) -> bytes | None:
    if _fetchable(url):
        return None
    try:
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, stream=True)
        response.raise_for_status()
        if not response.headers.get("Content-Type", "").lower().startswith("image/"):
            return None
        body = bytearray()
        for chunk in response.iter_content(64 * 1024):
            body.extend(chunk)
            if len(body) > MAX_IMAGE_BYTES:
                return None
        return bytes(body)
    except Exception:
        return None


def _ytdlp_metadata(page_url: str) -> dict | None:
    """Ask yt-dlp's site extractor for thumbnail, media URL and upload date.

    Instagram, Facebook and X serve client-rendered shells to a plain GET, so
    HTML scraping finds nothing even on a genuine match. yt-dlp reads these
    properly through the platforms' own public endpoints.
    """
    if shutil.which("yt-dlp") is None:
        return None
    try:
        completed = subprocess.run(
            ["yt-dlp", "--no-playlist", "--skip-download", "--dump-json", page_url],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            timeout=YTDLP_METADATA_TIMEOUT, check=False,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return None
        info = json.loads(completed.stdout.strip().splitlines()[0])
        upload_date = info.get("upload_date") or ""
        published_at = (f"{upload_date[0:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
                        if len(upload_date) == 8 else None)
        return {
            "thumbnail": info.get("thumbnail"),
            "video_url": info.get("url"),
            "published_at": published_at,
            "uploader": info.get("uploader") or info.get("channel"),
        }
    except Exception:
        return None


def _ytdlp_video(page_url: str) -> dict | None:
    if not FETCH_CANDIDATE_VIDEO or shutil.which("yt-dlp") is None:
        return None
    temp_dir = tempfile.mkdtemp(prefix="deeptrace_prov_")
    command = ["yt-dlp", "--no-playlist", "--max-filesize", str(MAX_VIDEO_BYTES),
               "--format", "best[ext=mp4]/best",
               "--output", os.path.join(temp_dir, "candidate.%(ext)s")]
    if shutil.which("deno"):
        command += ["--js-runtimes", "deno"]
    command.append(page_url)
    try:
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, timeout=YTDLP_VIDEO_TIMEOUT, check=False)
        if completed.returncode != 0:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None
        files = [os.path.join(temp_dir, name) for name in os.listdir(temp_dir)
                 if os.path.isfile(os.path.join(temp_dir, name))]
        if not files:
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None
        return {"path": max(files, key=os.path.getsize), "cleanup": temp_dir}
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None


def _compare_candidate_video(reference: dict, candidate_path: str) -> dict | None:
    """Compare a downloaded candidate video frame-by-frame against the reference."""
    try:
        frames = _sample_video_frames(candidate_path, VERIFY_FRAME_INTERVAL, 30)
    except Exception:
        return None
    if not frames:
        return None

    # Each candidate frame is hashed once, not once per reference frame.
    candidates = [{"index": frame["index"], "timestamp": frame["timestamp"],
                   "hashes": _hashes(frame["image"]), "image": frame["image"]}
                  for frame in frames]

    matches = []
    for entry in reference["frames"]:
        best = None
        for candidate in candidates:
            media = _compare_hashes(entry["hashes"], candidate["hashes"])
            if best is None or media["combined_score"] > best["media"]["combined_score"]:
                best = {"reference_frame": entry["frame"], "reference_timestamp": entry["timestamp"],
                        "candidate_frame": candidate["index"],
                        "candidate_timestamp": candidate["timestamp"],
                        "media": media, "image": candidate["image"]}
        if best:
            matches.append(best)

    face_matches = 0
    best_face = None
    if reference["face_embeddings"]:
        for match in matches:
            if match["media"]["combined_score"] < FACE_SUPPORT_MIN_MEDIA:
                continue
            face = _compare_faces(reference["face_embeddings"], _face_embedding(match["image"]))
            match["face"] = {key: value for key, value in face.items()}
            if face["status"] == "FACE_MATCH":
                face_matches += 1
            if face["similarity"] is not None and (best_face is None or face["similarity"] > best_face):
                best_face = face["similarity"]
    for match in matches:
        match.pop("image", None)

    scores = [match["media"]["combined_score"] for match in matches]
    strong = [match for match in matches if match["media"]["combined_score"] >= VIDEO_FRAME_THRESHOLD]
    frame_ratio = len(strong) / len(matches) if matches else 0.0
    face_ratio = face_matches / len(matches) if matches else 0.0

    if frame_ratio >= VIDEO_FRAME_MATCH_RATIO:
        classification = ("SAME_MEDIA_AND_PERSON" if face_ratio >= FACE_MATCH_RATIO
                          else "SAME_OR_NEAR_DUPLICATE_MEDIA")
    elif face_ratio >= FACE_MATCH_RATIO:
        classification = "SAME_PERSON_DIFFERENT_MEDIA"
    else:
        classification = "NO_MATCH"

    return {
        "classification": classification,
        "frames_compared": len(matches),
        "strong_frame_matches": len(strong),
        "frame_match_ratio": round(frame_ratio, 4),
        "face_match_ratio": round(face_ratio, 4),
        "best_face_similarity": best_face,
        "average_frame_score": round(float(np.mean(scores)), 4) if scores else 0.0,
        "best_frame_score": round(max(scores), 4) if scores else 0.0,
        "verified": (classification in ("SAME_MEDIA_AND_PERSON", "SAME_OR_NEAR_DUPLICATE_MEDIA")
                     and frame_ratio >= VIDEO_FRAME_MATCH_RATIO),
    }


def _confidence(record: dict) -> float:
    """An ordering aid, not a probability — named as such everywhere it appears."""
    media = record.get("media_score") or 0.0
    face = record.get("face_similarity") or 0.0
    recurrence = min(1.0, record.get("frame_occurrence_count", 0) / 3.0)
    temporal = 1.0 if (record.get("published_at") or record.get("first_observed")) else 0.0
    return round(max(0.0, min(1.0, 0.45 * media + 0.20 * recurrence
                              + 0.15 * max(0.0, face) + 0.20 * temporal)), 3)


def _classify(record: dict) -> str:
    if not record.get("media_verified"):
        return "UNVERIFIED" if record.get("media_examined") else "NO_MATCH"
    if record.get("first_observed"):
        return "LIKELY_EARLIEST_OBSERVED"
    return "MATCHING_SOURCE"


def _verify_source(source: dict, reference: dict) -> dict:
    url = source["url"]
    record = {
        "url": url,
        "title": source.get("title"),
        "publisher": source.get("publisher"),
        "platform": source.get("platform") or platform_for(url),
        "rank_score": source.get("rank_score"),
        "found_by_frames": source.get("found_by_frames", []),
        "frame_occurrence_count": source.get("frame_occurrence_count", 0),
        "checked_at": _now(),
        "status": "unverified",
        "media_verified": False,
        "media_examined": 0,
        "images_checked": 0,
        "videos_examined": 0,
        "media_score": None,
        "face_similarity": None,
        "published_at": None,
        "first_observed": None,
    }

    refusal = _fetchable(url)
    if refusal:
        record.update({"status": "refused", "reason": refusal})
        record["provenance_estimate"] = {
            "classification": "NOT_RETRIEVED",
            "confidence_score": 0.0,
            "confidence_type": "engineering_score_not_probability",
        }
        return record

    images: list[str] = []
    videos: list[str] = []
    resolved = url

    if record["platform"] in SOCIAL_PLATFORMS:
        meta = _ytdlp_metadata(url)
        if meta:
            record["uploader"] = meta.get("uploader")
            record["published_at"] = meta.get("published_at")
            record["metadata_source"] = "yt-dlp site extractor"
            if meta.get("thumbnail"):
                images.append(meta["thumbnail"])
            if meta.get("video_url"):
                videos.append(meta["video_url"])

    try:
        resolved, http_status, body = _fetch_page(url)
        html = body.decode("utf-8", errors="ignore")
        scraped = _extract_page_media(resolved, html)
        images += [item for item in scraped["images"] if item not in images]
        videos += [item for item in scraped["videos"] if item not in videos]
        record["resolved_url"] = resolved
        record["http_status"] = http_status
        if not record["published_at"]:
            record["published_at"] = _extract_published_at(html)
            if record["published_at"]:
                record["metadata_source"] = "page metadata"
    except Exception as error:
        record["page_error"] = str(error)
        if not images and not videos:
            record.update({
                "status": "unreachable",
                "reason": ("The page could not be retrieved, so nothing on it was compared. "
                           "This is not evidence that the media is absent from it."),
            })
            record["provenance_estimate"] = {
                "classification": "NOT_RETRIEVED",
                "confidence_score": 0.0,
                "confidence_type": "engineering_score_not_probability",
            }
            return record

    archived = _wayback_first_observed(resolved)
    if archived:
        record["first_observed"] = archived["timestamp"]
        record["wayback"] = archived

    best: dict | None = None
    for image_url in images:
        record["images_checked"] += 1
        data = _download_image(image_url)
        if not data:
            continue
        image = _load_image_bytes(data)
        if image is None:
            continue
        match = _compare_candidate_image(reference, image)
        if not match:
            continue
        record["media_examined"] += 1
        candidate = {
            "media_type": "image",
            "media_url": image_url,
            "media_sha256": _sha256_bytes(data),
            "score": match["combined_score"],
            "media_score": match["media"]["combined_score"],
            "face": match["face"],
            "reference_frame": match["reference_frame"],
            "reference_timestamp": match["reference_timestamp"],
            "verified": match["combined_score"] >= MEDIA_THRESHOLD,
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate

    video_result = None
    for video_url in videos[:1] if FETCH_CANDIDATE_VIDEO else []:
        acquired = _ytdlp_video(resolved) or None
        if not acquired:
            continue
        try:
            record["videos_examined"] += 1
            comparison = _compare_candidate_video(reference, acquired["path"])
            if comparison:
                comparison["media_url"] = video_url
                comparison["media_sha256"] = _sha256_file(acquired["path"])
                video_result = comparison
        finally:
            shutil.rmtree(acquired["cleanup"], ignore_errors=True)

    if video_result:
        record["video_comparison"] = video_result
        record["media_examined"] += 1

    verified_video = bool(video_result and video_result.get("verified"))
    verified_image = bool(best and best["verified"])

    if verified_video:
        record.update({
            "status": "provenance_candidate",
            "media_verified": True,
            "verified_on": "candidate video",
            "media_score": video_result["best_frame_score"],
            "face_similarity": video_result.get("best_face_similarity"),
            "classification": video_result["classification"],
            "media_url": video_result.get("media_url"),
            "media_sha256": video_result.get("media_sha256"),
        })
    elif verified_image:
        record.update({
            "status": "provenance_candidate",
            "media_verified": True,
            # Named precisely: a thumbnail match says the page advertises this
            # frame, not that the page serves this video.
            "verified_on": "page image or thumbnail",
            "media_score": best["media_score"],
            "face_similarity": best["face"].get("similarity"),
            "classification": ("SAME_MEDIA_AND_PERSON" if best["face"].get("status") == "FACE_MATCH"
                               else "SAME_OR_NEAR_DUPLICATE_MEDIA"),
            "media_url": best["media_url"],
            "media_sha256": best["media_sha256"],
            "matched_reference_frame": best["reference_frame"],
            "matched_reference_timestamp": best["reference_timestamp"],
        })
    else:
        record.update({
            "status": "no_match" if record["media_examined"] else "unverified",
            "media_score": best["media_score"] if best else None,
            "face_similarity": best["face"].get("similarity") if best else None,
            "reason": ("Media on this page was retrieved and compared but did not meet the "
                       f"similarity threshold of {MEDIA_THRESHOLD}."
                       if record["media_examined"] else
                       "No comparable media could be retrieved from this page."),
        })

    record["provenance_estimate"] = {
        "classification": _classify(record),
        "confidence_score": _confidence(record),
        "confidence_type": "engineering_score_not_probability",
        "limitation": ("The earliest observed source is not guaranteed to be the original source "
                       "or the first upload."),
    }
    return record


def verify(sources: list[dict], reference: dict) -> list[dict]:
    """Fetch and locally compare each lead. Order of the input list is preserved."""
    numbered: list[tuple[int, dict]] = []
    with ThreadPoolExecutor(max_workers=MAX_CRAWL_WORKERS) as pool:
        futures = {}
        for position, source in enumerate(sources):
            futures[pool.submit(_verify_source, source, reference)] = (position, source)
        for future in as_completed(futures):
            position, source = futures[future]
            try:
                numbered.append((position, future.result()))
            except Exception as error:
                numbered.append((position, {
                    "url": source.get("url"),
                    "platform": platform_for(source.get("url", "")),
                    "status": "error",
                    "reason": f"Verification failed: {error}",
                    "media_verified": False,
                    "checked_at": _now(),
                }))
    numbered.sort(key=lambda pair: pair[0])
    return [record for _, record in numbered]


# ── Entry point used by the analysis pipeline ────────────────────────────────

def estimate(file_path: str, media_type: str) -> dict:
    """Discover candidate sources, verify them locally, and summarise honestly."""
    started = _now()
    scope = ("Reverse-image discovery through one third-party index, followed by local "
             "verification of the media each candidate page actually serves. Not an "
             "internet-wide search; no private or authenticated endpoint is accessed.")

    if not os.path.isfile(file_path):
        return {"status": "failed", "scope": scope, "started_at": started,
                "reason": "The media file is no longer present for provenance search.",
                "sources": [], "limitations": LIMITATIONS}

    discovery = discover(file_path, media_type)
    if discovery["status"] != "completed":
        return {
            "status": discovery["status"],
            "scope": scope,
            "started_at": started,
            "reason": discovery.get("reason"),
            "engine": "Google Lens via SerpApi",
            "sources": [],
            "sources_discovered": 0,
            "sources_verified": 0,
            "limitations": LIMITATIONS,
        }

    leads = discovery["sources"]
    if not leads:
        return {
            "status": "no_sources",
            "scope": scope,
            "started_at": started,
            "engine": discovery["engine"],
            "method": discovery["method"],
            "queries": discovery["queries"],
            "frames_searched": discovery["frames_searched"],
            "raw_match_count": discovery["raw_match_count"],
            "sources": [],
            "sources_discovered": 0,
            "sources_verified": 0,
            "reason": ("The reverse-image index returned no visually similar pages. That is not "
                       "evidence the media was never published — only that this index holds no "
                       "match for the frames sampled."),
            "limitations": LIMITATIONS,
        }

    try:
        reference = build_reference_signature(file_path, media_type)
    except Exception as error:
        # Leads without local verification are still leads, and suppressing them
        # would hide real discovery output — but they must not be called verified.
        return {
            "status": "discovered_only",
            "scope": scope,
            "started_at": started,
            "engine": discovery["engine"],
            "method": discovery["method"],
            "queries": discovery["queries"],
            "frames_searched": discovery["frames_searched"],
            "raw_match_count": discovery["raw_match_count"],
            "unique_source_count": discovery["unique_source_count"],
            "sources_discovered": len(leads),
            "sources_verified": 0,
            "sources": [dict(lead, status="not_verified") for lead in leads],
            "reason": f"Candidate sources were discovered but could not be verified locally: {error}",
            "limitations": LIMITATIONS,
        }

    checked = verify(leads[:VERIFY_MAX_SOURCES], reference)
    unchecked = [dict(lead, status="not_checked",
                      reason=f"Outside the top {VERIFY_MAX_SOURCES} ranked leads this run verified.")
                 for lead in leads[VERIFY_MAX_SOURCES:]]
    records = checked + unchecked

    candidates = [item for item in records if item.get("media_verified")]
    earliest = None
    dated = [item for item in candidates if item.get("first_observed")]
    if dated:
        earliest = min(dated, key=lambda item: str(item["first_observed"]))

    return {
        "status": "completed",
        "scope": scope,
        "started_at": started,
        "completed_at": _now(),
        "engine": discovery["engine"],
        "method": discovery["method"],
        "verification_method": (
            "Each candidate page was fetched by DeepTrace and the media it serves compared against "
            f"{reference['frames_sampled']} reference frame(s) using pHash, dHash and aHash "
            f"(threshold {MEDIA_THRESHOLD})"
            + (f", with FaceNet face support on {reference['frames_with_face']} frame(s) that "
               f"contained a detectable face (threshold {FACE_THRESHOLD})."
               if reference["frames_with_face"] else
               ". No detectable face was present in the reference media, so no facial support was available.")
        ),
        "candidate_video_download": ("enabled" if FETCH_CANDIDATE_VIDEO else
                                     "disabled — page images and thumbnails only"),
        "queries": discovery["queries"],
        "frames_searched": discovery["frames_searched"],
        "frames_failed": discovery["frames_failed"],
        "raw_match_count": discovery["raw_match_count"],
        "unique_source_count": discovery["unique_source_count"],
        "reference_frames_sampled": reference["frames_sampled"],
        "reference_frames_with_face": reference["frames_with_face"],
        "sources_discovered": len(leads),
        "sources_checked": len(checked),
        "sources_verified": len(candidates),
        "sources_unreachable": len([item for item in records if item.get("status") in
                                    ("unreachable", "refused")]),
        "earliest_observed_url": earliest["url"] if earliest else None,
        "earliest_observed_at": earliest["first_observed"] if earliest else None,
        "sources": records,
        "interpretation": _interpretation(len(leads), candidates, earliest),
        "limitations": LIMITATIONS,
    }


def _archive_date(stamp: str | None) -> str:
    """Wayback CDX stamps are YYYYMMDDhhmmss, which reads as an ID, not a date.

    Left verbatim when it is not that shape, rather than silently reformatted
    into something the archive never said.
    """
    text = str(stamp or "")
    if len(text) >= 8 and text[:8].isdigit():
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _interpretation(discovered: int, candidates: list[dict], earliest: dict | None) -> str:
    if not discovered:
        return ("No visually similar pages were returned for the frames sampled.")
    if not candidates:
        return (f"{discovered} visually similar page(s) were discovered, but none served media that "
                f"matched this file above the {MEDIA_THRESHOLD} similarity threshold. Treat them as "
                "leads to review manually, not as confirmed copies.")
    line = (f"{len(candidates)} of {discovered} discovered page(s) served media matching this file. "
            "A match establishes that the same or near-identical media appears there; it does not "
            "establish who published it or which copy came first.")
    if earliest:
        line += (f" The earliest archived capture among them is "
                 f"{_archive_date(earliest['first_observed'])} at {earliest['url']} — earliest "
                 "observed, not necessarily original.")
    return line
