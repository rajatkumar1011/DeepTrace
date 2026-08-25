"""Security boundaries.

One test per hardening requirement, asserting the security *property* rather
than the current implementation string, so a future refactor of the sanitiser
does not silently weaken the guarantee.
"""

import io
import os

import pytest

from paths import EVIDENCE_DIR, PROJECT_ROOT, repo_relative, resolve_inside, to_public_path
from services.forensics import calculate_sha256, stream_to_disk
from services.tracing import ALLOWED_SCHEMES, MAX_URLS_PER_REQUEST, parse_source_urls, validate_public_url


# ── Filename sanitisation and path traversal ─────────────────────────────────

TRAVERSAL_NAMES = [
    "../../../../etc/passwd",
    "..\\..\\..\\Windows\\System32\\config\\SAM",
    "/absolute/evil.mp4",
    "C:\\Windows\\evil.mp4",
    "....//....//evil.mp4",
    "video.mp4/../../../escape.mp4",
]


@pytest.mark.parametrize("raw", TRAVERSAL_NAMES)
def test_safe_filename_cannot_escape_its_directory(raw):
    """A sanitised name must be a bare basename that stays inside the target dir."""
    from main import safe_filename

    cleaned = safe_filename(raw)
    assert os.sep not in cleaned and "/" not in cleaned and "\\" not in cleaned
    assert ".." not in cleaned
    assert not os.path.isabs(cleaned)
    # The decisive check: joining it to a directory keeps it inside that directory.
    assert resolve_inside(EVIDENCE_DIR, cleaned) is not None


def test_safe_filename_strips_shell_and_control_characters():
    from main import safe_filename

    cleaned = safe_filename('clip"; rm -rf / #$(whoami)`id`.mp4')
    assert all(character.isalnum() or character in "._-" for character in cleaned)
    assert cleaned.endswith(".mp4")


def test_safe_filename_falls_back_when_nothing_survives():
    from main import safe_filename

    assert safe_filename("../../..") == "upload"
    assert safe_filename(None) == "upload"
    assert safe_filename("") == "upload"


def test_safe_filename_bounds_length():
    from main import safe_filename

    cleaned = safe_filename("a" * 5000 + ".mp4")
    assert len(cleaned) <= 112


def test_resolve_inside_rejects_escapes_and_allows_children():
    assert resolve_inside(EVIDENCE_DIR, "frames/frame_0.jpg") is not None
    assert resolve_inside(EVIDENCE_DIR, "../deeptrace.db") is None
    assert resolve_inside(EVIDENCE_DIR, "../../etc/passwd") is None
    assert resolve_inside(EVIDENCE_DIR, os.path.join(PROJECT_ROOT, "deeptrace.db")) is None


# ── No internal filesystem paths in API payloads ─────────────────────────────

def test_public_paths_never_expose_absolute_locations():
    inside = os.path.join(EVIDENCE_DIR, "frames", "frame_0.jpg")
    public = to_public_path(inside)
    assert public == "evidence/frames/frame_0.jpg"
    assert not os.path.isabs(public)
    assert PROJECT_ROOT not in public


def test_paths_outside_served_roots_are_withheld_not_guessed():
    assert to_public_path("/etc/passwd") is None
    assert to_public_path(None) is None
    assert repo_relative(os.path.join(PROJECT_ROOT, "..", "outside.txt")) is None


# ── Size cap and server-side hashing ─────────────────────────────────────────

def test_stream_to_disk_aborts_past_the_cap_and_leaves_no_partial_file(tmp_path):
    destination = str(tmp_path / "oversize.bin")
    assert stream_to_disk(io.BytesIO(b"x" * 4096), destination, max_bytes=1024) is None
    assert not os.path.exists(destination), "a rejected upload must not persist"


def test_hash_is_computed_from_persisted_bytes_not_supplied_by_the_client(tmp_path):
    """The recorded digest must describe what actually landed on disk."""
    payload = b"forensic payload"
    destination = str(tmp_path / "kept.bin")
    size, digest = stream_to_disk(io.BytesIO(payload), destination, max_bytes=1_000_000)

    assert size == len(payload)
    # Independently recomputed by re-reading the file, so the digest is proven to
    # describe the persisted bytes. The algorithm itself is pinned by the
    # known-answer test below.
    assert digest == calculate_sha256(destination)
    assert len(digest) == 64


def test_hash_of_known_input_matches_reference_value(tmp_path):
    """Pin the algorithm: SHA-256 of b'abc' is a published constant."""
    path = tmp_path / "abc.bin"
    path.write_bytes(b"abc")
    assert calculate_sha256(str(path)) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


# ── URL validation (SSRF) ────────────────────────────────────────────────────

BLOCKED_URLS = [
    "http://example.com/clip.mp4",              # plaintext scheme
    "ftp://example.com/clip.mp4",               # non-HTTP scheme
    "file:///etc/passwd",                       # local file
    "https://127.0.0.1/clip.mp4",               # loopback
    "https://localhost/clip.mp4",               # loopback by name
    "https://10.0.0.5/clip.mp4",                # RFC1918
    "https://192.168.1.1/admin",                # RFC1918
    "https://172.16.0.1/clip.mp4",              # RFC1918
    "https://169.254.169.254/latest/meta-data/",  # cloud metadata service
    "https://[::1]/clip.mp4",                   # IPv6 loopback
    "https://0.0.0.0/clip.mp4",                 # unspecified
]

# The matching accept case (a public https host returning None) is not asserted
# here because it requires DNS resolution and would make the suite fail offline.
# It was verified manually: https://example.com/clip.mp4 validates to None, so the
# refusals below are discriminating rather than a blanket reject.


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_private_and_non_https_targets_are_refused_with_a_reason(url):
    reason = validate_public_url(url)
    assert reason, f"{url} must be refused"
    assert isinstance(reason, str) and reason.strip()


def test_only_https_is_permitted():
    assert ALLOWED_SCHEMES == {"https"}


def test_source_url_list_is_bounded():
    many = "\n".join(f"https://example.com/{index}.mp4" for index in range(50))
    assert len(parse_source_urls(many)) <= MAX_URLS_PER_REQUEST


def test_source_url_parsing_tokenises_and_deduplicates():
    """Parsing only splits and dedupes; validation is a separate, later gate."""
    parsed = parse_source_urls("https://a.example/x.mp4, https://a.example/x.mp4\nhttps://b.example/y.mp4")
    assert parsed == ["https://a.example/x.mp4", "https://b.example/y.mp4"]
    assert parse_source_urls("   \n  \n ") == []
    assert parse_source_urls(None) == []


@pytest.mark.parametrize("junk", ["not a url", "javascript:alert(1)", "://malformed", "..", "%00"])
def test_anything_that_survives_parsing_is_still_refused_before_fetching(junk):
    """The two layers together: a non-URL token can never reach a network call."""
    survivors = parse_source_urls(junk)
    assert survivors, "the parser is expected to pass this token through to validation"
    for candidate in survivors:
        assert validate_public_url(candidate), f"{candidate!r} must be refused"
