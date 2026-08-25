"""Public-source tracing and copy comparison.

Scope, stated plainly because it is easy to overstate: DeepTrace does **not**
search the internet and does not access any platform's private APIs. An
investigator supplies a public URL (or a local copy they already hold); DeepTrace
retrieves that one resource over plain HTTPS, preserves it as evidence, and
compares it to the original using hashes. Nothing here bypasses authentication,
robots restrictions or access controls.

Retrieval is treated as an SSRF-sensitive operation: only https, only
public-routable addresses, redirects re-validated, size-capped, streamed to disk.
"""

import ipaddress
import json
import os
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, OpenerDirector, Request
from uuid import uuid4

from services.forensics import (
    audio_fingerprint,
    calculate_perceptual_hash,
    calculate_sha256,
    compare_audio_fingerprints,
    phash_similarity,
    similarity_label,
)

MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 15
MAX_REDIRECTS = 3
MAX_URLS_PER_REQUEST = 8
ALLOWED_SCHEMES = {"https"}
USER_AGENT = "DeepTrace/1.0 (forensic evidence prototype; +local use)"

_ALLOWED_EXTENSIONS = {
    ".mp4", ".avi", ".mov", ".mkv", ".webm",
    ".jpg", ".jpeg", ".png", ".bmp", ".webp",
    ".wav", ".mp3", ".flac", ".ogg", ".m4a",
}


def parse_source_urls(raw) -> list[str]:
    """Accept a JSON array, newline list or comma list from the form field."""
    if raw is None:
        return []
    if isinstance(raw, list):
        values = raw
    else:
        text = str(raw).strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                values = json.loads(text)
            except json.JSONDecodeError:
                values = [line.strip() for line in text.splitlines() if line.strip()]
        else:
            values = [line.strip() for line in text.replace(",", "\n").splitlines() if line.strip()]

    seen: list[str] = []
    for item in values:
        url = str(item).strip()
        if url and url not in seen:
            seen.append(url)
    return seen[:MAX_URLS_PER_REQUEST]


def _address_is_public(host: str) -> tuple[bool, str | None]:
    """Reject hosts that resolve to any non-public address.

    Guards against server-side request forgery: a URL such as
    ``https://internal.example/`` that resolves to 127.0.0.1 or 169.254.169.254
    would otherwise let a caller reach services on the host running DeepTrace.
    """
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as error:
        return False, f"Host could not be resolved ({error.strerror or error})."
    if not infos:
        return False, "Host could not be resolved."

    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return False, f"Host resolved to an address that could not be parsed ({address})."
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False, (
                "Host resolves to a non-public address, which DeepTrace does not fetch."
            )
    return True, None


def validate_public_url(url: str) -> str | None:
    """Return an error string, or None when the URL is acceptable to fetch."""
    if len(url) > 2048:
        return "URL is longer than 2048 characters."
    try:
        parsed = urlparse(url)
    except ValueError:
        return "URL could not be parsed."

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return "Only https:// URLs are retrieved."
    if not parsed.netloc:
        return "URL host is missing."
    if parsed.username or parsed.password:
        return "URLs containing embedded credentials are not retrieved."

    host = (parsed.hostname or "").lower()
    if not host:
        return "URL host is missing."
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal", ".localhost")):
        return "Local and internal hostnames are not fetched."

    ok, reason = _address_is_public(host)
    return None if ok else reason


class _ValidatingRedirectHandler(HTTPRedirectHandler):
    """Re-run URL validation on every redirect hop."""

    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        error = validate_public_url(newurl)
        if error:
            raise URLError(f"Redirect to a disallowed target was blocked: {error}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener() -> OpenerDirector:
    opener = OpenerDirector()
    opener.add_handler(HTTPSHandler())
    opener.add_handler(_ValidatingRedirectHandler())
    return opener


def _safe_extension(url: str, content_type: str | None) -> str:
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    if ext in _ALLOWED_EXTENSIONS:
        return ext
    mapping = {
        "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
        "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
        "audio/wav": ".wav", "audio/mpeg": ".mp3", "audio/mp4": ".m4a",
    }
    return mapping.get((content_type or "").split(";")[0].strip().lower(), ".bin")


def fetch_public_url(url: str, dest_dir: str) -> dict:
    """Retrieve one public HTTPS resource, streamed to disk under a size cap."""
    error = validate_public_url(url)
    if error:
        return {"url": url, "status": "rejected", "error": error}

    os.makedirs(dest_dir, exist_ok=True)
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    dest_path = None
    try:
        with _opener().open(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("Content-Type", "") or ""
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > MAX_DOWNLOAD_BYTES:
                return {
                    "url": url, "status": "rejected",
                    "error": f"Remote file is {int(declared) / 1048576:.1f} MB, above the 25 MB cap.",
                }

            dest_path = os.path.join(dest_dir, f"{uuid4().hex}{_safe_extension(url, content_type)}")
            total = 0
            with open(dest_path, "wb") as handle:
                while True:
                    block = response.read(65536)
                    if not block:
                        break
                    total += len(block)
                    if total > MAX_DOWNLOAD_BYTES:
                        handle.close()
                        _remove(dest_path)
                        return {"url": url, "status": "rejected",
                                "error": "Download exceeded the 25 MB cap and was aborted."}
                    handle.write(block)

        if total == 0:
            _remove(dest_path)
            return {"url": url, "status": "failed", "error": "The remote server returned an empty body."}

        return {
            "url": url,
            "status": "fetched",
            "file_path": dest_path,
            "bytes": total,
            "content_type": content_type.split(";")[0].strip() or None,
            "final_url": url,
        }
    except HTTPError as http_error:
        _remove(dest_path)
        return {"url": url, "status": "failed",
                "error": f"The server responded {http_error.code} {http_error.reason}."}
    except URLError as url_error:
        _remove(dest_path)
        return {"url": url, "status": "failed", "error": str(url_error.reason)[:300]}
    except socket.timeout:
        _remove(dest_path)
        return {"url": url, "status": "failed",
                "error": f"The request timed out after {FETCH_TIMEOUT_SECONDS}s."}
    except Exception as unexpected:
        _remove(dest_path)
        return {"url": url, "status": "failed", "error": str(unexpected)[:300]}


def _remove(path: str | None) -> None:
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def classify_copy(original_sha256: str | None, original_phash: str | None,
                  original_audio_fp, copy_path: str, media_type: str) -> dict:
    """Compare a retrieved copy against the case original using hashes only."""
    copy_sha = calculate_sha256(copy_path)
    copy_phash = None
    audio_similarity = None

    if media_type in {"image", "video"}:
        copy_phash = calculate_perceptual_hash(copy_path)
    if media_type in {"audio", "video"} and original_audio_fp:
        audio_similarity = compare_audio_fingerprints(original_audio_fp, audio_fingerprint(copy_path))

    match_type = "none"
    similarity = 0.0
    basis = "No comparable hash could be computed for this pair."

    if original_sha256 and copy_sha and copy_sha == original_sha256:
        match_type = "exact"
        similarity = 1.0
        basis = "SHA-256 digests are identical — the retrieved bytes are the same file."
    elif original_phash and copy_phash:
        similarity = phash_similarity(original_phash, copy_phash)
        basis = (
            f"Perceptual hash agreement is {similarity * 100:.1f}% "
            "(visual similarity, robust to re-encoding and rescaling)."
        )
        if similarity >= 0.95:
            match_type = "near"
        elif similarity >= 0.80:
            match_type = "similar"
    if match_type == "none" and audio_similarity and audio_similarity > 0.9:
        match_type = "near"
        similarity = max(similarity, float(audio_similarity))
        basis = f"Audio fingerprint agreement is {audio_similarity * 100:.1f}%."

    return {
        "sha256": copy_sha,
        "perceptual_hash": copy_phash,
        "audio_fingerprint_similarity": round(audio_similarity, 4) if audio_similarity is not None else None,
        "match_type": match_type,
        "similarity": round(float(similarity), 4),
        "similarity_label": "Byte-identical" if match_type == "exact" else similarity_label(similarity),
        "basis": basis,
    }
