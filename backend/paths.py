"""Absolute filesystem anchors for DeepTrace.

Every service resolves paths through this module so the backend behaves the same
whether it is launched from the repository root, from ``backend/``, or by a test
runner. Relative paths previously created duplicate ``backend/uploads`` and
``backend/evidence`` trees.
"""

import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
UPLOAD_DIR = os.path.join(PROJECT_ROOT, "uploads")
IDENTITY_DIR = os.path.join(UPLOAD_DIR, "identities")
EVIDENCE_DIR = os.path.join(PROJECT_ROOT, "evidence")
FRAMES_DIR = os.path.join(EVIDENCE_DIR, "frames")
AUDIO_DIR = os.path.join(EVIDENCE_DIR, "audio")
LOCALIZATION_DIR = os.path.join(EVIDENCE_DIR, "localization")
SOURCES_DIR = os.path.join(EVIDENCE_DIR, "sources")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
REPORTS_DIR = os.path.join(DATA_DIR, "reports")
DEMO_DIR = os.path.join(DATA_DIR, "demo")
BENCHMARK_DIR = os.path.join(DATA_DIR, "benchmark")

_SERVED_ROOTS = {
    "evidence": EVIDENCE_DIR,
    "uploads": UPLOAD_DIR,
}


def ensure_runtime_dirs() -> None:
    for path in (
        UPLOAD_DIR,
        IDENTITY_DIR,
        EVIDENCE_DIR,
        FRAMES_DIR,
        AUDIO_DIR,
        LOCALIZATION_DIR,
        SOURCES_DIR,
        REPORTS_DIR,
        DEMO_DIR,
    ):
        os.makedirs(path, exist_ok=True)


def report_path(investigation_id: int) -> str:
    return os.path.join(REPORTS_DIR, f"DeepTrace_Report_INV{investigation_id}.pdf")


def to_public_path(path: str | None) -> str | None:
    """Convert an absolute artifact path into a repository-relative POSIX path.

    API responses must never leak absolute filesystem paths (they expose the
    operator's directory layout). Anything outside a served root is reported as
    ``None`` rather than guessed at.
    """
    if not path:
        return None
    absolute = os.path.abspath(path)
    for prefix, root in _SERVED_ROOTS.items():
        try:
            relative = os.path.relpath(absolute, root)
        except ValueError:
            continue
        if not relative.startswith(".."):
            return f"{prefix}/{relative}".replace(os.sep, "/")
    return None


def to_static_url(path: str | None) -> str | None:
    """Browser-reachable URL for an artifact served by the static mounts."""
    public = to_public_path(path)
    return f"/{public}" if public else None


def repo_relative(path: str | None) -> str | None:
    """Repository-relative POSIX path for artifacts outside the served roots.

    Used for generated reports, which are downloaded through an API endpoint
    rather than a static mount. Returns ``None`` for anything outside the
    repository so an absolute filesystem path can never be returned.
    """
    if not path:
        return None
    try:
        relative = os.path.relpath(os.path.abspath(path), PROJECT_ROOT)
    except ValueError:
        return None
    if relative.startswith(".."):
        return None
    return relative.replace(os.sep, "/")


def resolve_inside(root: str, candidate: str) -> str | None:
    """Resolve ``candidate`` and return it only if it stays inside ``root``."""
    absolute = os.path.abspath(os.path.join(root, candidate))
    root_abs = os.path.abspath(root)
    if absolute == root_abs or absolute.startswith(root_abs + os.sep):
        return absolute
    return None
