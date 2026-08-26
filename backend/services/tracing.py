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
from http.client import HTTPSConnection
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import (
    HTTPDefaultErrorHandler,
    HTTPErrorProcessor,
    HTTPRedirectHandler,
    HTTPSHandler,
    OpenerDirector,
    Request,
)
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

# Content types DeepTrace will preserve as media. An error page, a login
# redirect or a JSON API envelope must not be written into the evidence store
# and hashed as though it were the traced copy: it would carry a real SHA-256,
# a real timestamp and a real custody entry while being none of the thing it
# claims to be. Anything outside this set is refused rather than saved as .bin.
_ALLOWED_CONTENT_TYPES = {
    "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/pjpeg": ".jpg",
    "image/png": ".png", "image/webp": ".webp", "image/bmp": ".bmp",
    "video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov",
    "video/x-msvideo": ".avi", "video/x-matroska": ".mkv",
    "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/wave": ".wav",
    "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/mp4": ".m4a",
    "audio/aac": ".m4a", "audio/flac": ".flac", "audio/x-flac": ".flac",
    "audio/ogg": ".ogg",
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


def _resolve_public_addresses(host: str) -> tuple[list[str], str | None]:
    """Resolve a host and refuse it unless every answer is public-routable.

    Guards against server-side request forgery: a URL such as
    ``https://internal.example/`` that resolves to 127.0.0.1 or 169.254.169.254
    would otherwise let a caller reach services on the host running DeepTrace.

    The resolved addresses are returned, not discarded, so the connection can be
    made to an address that was actually checked. Validating a hostname and then
    letting the TLS layer resolve it a second time leaves a window in which the
    second answer differs from the first — the address is pinned instead.
    """
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as error:
        return [], f"Host could not be resolved ({error.strerror or error})."
    if not infos:
        return [], "Host could not be resolved."

    addresses: list[str] = []
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return [], f"Host resolved to an address that could not be parsed ({address})."
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return [], (
                "Host resolves to a non-public address, which DeepTrace does not fetch."
            )
        if address not in addresses:
            addresses.append(address)
    return addresses, None


def _address_is_public(host: str) -> tuple[bool, str | None]:
    """Whether a host resolves entirely to public addresses."""
    addresses, reason = _resolve_public_addresses(host)
    return bool(addresses), reason


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


class _PinnedHTTPSConnection(HTTPSConnection):
    """Connect to an address that was already checked, but speak TLS to the host.

    ``self.host`` stays the real hostname, so ``HTTPSConnection.connect`` derives
    the correct ``server_hostname`` and certificate verification is unchanged.
    Only the socket target is replaced, with a literal IP the SSRF check already
    accepted. Without the pin, validation and connection each perform their own
    DNS lookup, and a host that answers with a public address on the first and a
    loopback address on the second would pass the check and still be fetched.
    """

    def __init__(self, host, *args, pinned_address=None, **kwargs):
        super().__init__(host, *args, **kwargs)
        self.pinned_address = pinned_address
        if pinned_address:
            self._create_connection = self._connect_to_pinned_address

    def _connect_to_pinned_address(self, address, timeout, source_address):
        """Ignore the hostname in ``address`` and dial the validated IP."""
        return socket.create_connection(
            (self.pinned_address, address[1]), timeout, source_address)


class _PinnedHTTPSHandler(HTTPSHandler):
    """An https handler that resolves once, checks, and connects to that answer."""

    def https_open(self, req):
        host = req.host.rsplit(":", 1)[0] if req.host.count(":") == 1 else req.host
        host = host.strip("[]")
        addresses, reason = _resolve_public_addresses(host)
        if reason or not addresses:
            raise URLError(reason or "Host could not be resolved.")
        pinned = addresses[0]

        def connection(host_arg, **kwargs):
            return _PinnedHTTPSConnection(host_arg, pinned_address=pinned, **kwargs)

        return self.do_open(connection, req, context=self._context,
                            check_hostname=self._check_hostname)


def _opener() -> OpenerDirector:
    """Build the one opener DeepTrace fetches through.

    HTTPErrorProcessor and HTTPDefaultErrorHandler are not optional extras. It is
    HTTPErrorProcessor that routes a non-2xx response into ``parent.error()``,
    which is the only path by which the redirect handlers registered below are
    ever reached, and HTTPDefaultErrorHandler that turns an unhandled error code
    into an HTTPError. Omit them and ``open()`` returns the raw response for any
    status: a 403 or 404 body is streamed to disk, hashed, and recorded in the
    evidence store as the traced copy, while every redirect goes unfollowed.
    """
    opener = OpenerDirector()
    opener.add_handler(_PinnedHTTPSHandler())
    opener.add_handler(HTTPErrorProcessor())
    opener.add_handler(HTTPDefaultErrorHandler())
    opener.add_handler(_ValidatingRedirectHandler())
    return opener


def _safe_extension(url: str, content_type: str | None) -> str | None:
    """The extension to preserve this response under, or None to refuse it.

    The declared content type decides. A path extension is honoured only when the
    server declared nothing usable, because a URL path is caller-controlled text
    and says nothing about what the server actually returned.
    """
    declared = (content_type or "").split(";")[0].strip().lower()
    if declared in _ALLOWED_CONTENT_TYPES:
        return _ALLOWED_CONTENT_TYPES[declared]
    if declared:
        return None
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    return ext if ext in _ALLOWED_EXTENSIONS else None


def fetch_public_url(url: str, dest_dir: str) -> dict:
    """Retrieve one public HTTPS resource, streamed to disk under a size cap.

    Only a 2xx response carrying a media content type is written to disk. Anything
    else — an error status, a login page, an HTML placeholder — is refused with the
    reason, because a file that reaches the evidence store gets a real digest and a
    real custody entry, and neither of those should ever describe an error page.
    """
    error = validate_public_url(url)
    if error:
        return {"url": url, "status": "rejected", "error": error}

    os.makedirs(dest_dir, exist_ok=True)
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    dest_path = None
    try:
        with _opener().open(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            # HTTPErrorProcessor raises for non-2xx, so reaching here means the
            # server returned success. Asserted rather than assumed: a future
            # change to the opener must fail loudly instead of preserving a 404.
            status = getattr(response, "status", None) or response.getcode()
            if status is not None and not 200 <= int(status) < 300:
                return {"url": url, "status": "failed",
                        "error": f"The server responded {status}, which is not a success status."}

            content_type = response.headers.get("Content-Type", "") or ""
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > MAX_DOWNLOAD_BYTES:
                return {
                    "url": url, "status": "rejected",
                    "error": f"Remote file is {int(declared) / 1048576:.1f} MB, above the 25 MB cap.",
                }

            extension = _safe_extension(url, content_type)
            if extension is None:
                return {
                    "url": url, "status": "rejected",
                    "error": (
                        f"The server returned {content_type.split(';')[0].strip() or 'no content type'}, "
                        "which is not image, video or audio. DeepTrace preserves only media as evidence."
                    ),
                }

            # geturl() is the address the bytes actually came from. Recording the
            # requested URL instead would put a claim in the evidence store that
            # the response never supported, once redirects are followed at all.
            final_url = response.geturl() or url

            dest_path = os.path.join(dest_dir, f"{uuid4().hex}{extension}")
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
            "final_url": final_url,
            "redirected": final_url != url,
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
    # Which comparisons were actually possible, so a "no match" can be read
    # correctly: no comparable channel is a different finding from a channel
    # that was compared and disagreed.
    channels: list[str] = ["SHA-256"] if copy_sha else []

    if media_type in {"image", "video"}:
        copy_phash = calculate_perceptual_hash(copy_path)
        if copy_phash and original_phash:
            channels.append("Perceptual hash")
    if media_type in {"audio", "video"} and original_audio_fp:
        audio_similarity = compare_audio_fingerprints(original_audio_fp, audio_fingerprint(copy_path))
        if audio_similarity is not None:
            channels.append("Audio fingerprint")

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
        "status": "completed",
        "method": (
            "SHA-256 exact match, then 64-bit perceptual hash (Hamming distance) for "
            "visual media and spectral fingerprint correlation for audio."
        ),
        "model_status": "Deterministic hash comparison (no ML model involved)",
        "scope": (
            "This compares one retrieved copy against the case original. It establishes "
            "whether the two files are the same or visually alike — not who published "
            "either, which came first, or how the copy was obtained."
        ),
        "compared_channels": channels,
        "sha256": copy_sha,
        "perceptual_hash": copy_phash,
        "audio_fingerprint_similarity": round(audio_similarity, 4) if audio_similarity is not None else None,
        "match_type": match_type,
        "similarity": round(float(similarity), 4),
        "similarity_label": "Byte-identical" if match_type == "exact" else similarity_label(similarity),
        "basis": basis,
    }
