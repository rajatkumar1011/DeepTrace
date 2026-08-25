"""Shared fixtures.

The database is redirected to a throwaway file *before* ``main`` is imported,
because ``backend/database.py`` reads ``DEEPTRACE_DB_PATH`` at import time and
builds the engine immediately. Importing the app first would bind the engine to
the operator's real ``deeptrace.db``.

These tests deliberately cover deterministic logic and rejection paths only. The
full model-backed pipeline is exercised by ``scripts/smoke_e2e.py``, which runs
against a live server; duplicating it here would make the suite slow and would
tie assertions to model outputs that legitimately vary with the media supplied.
"""

import os
import sys
import tempfile

import pytest

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REPO_ROOT = os.path.abspath(os.path.join(BACKEND_DIR, ".."))
for entry in (BACKEND_DIR, REPO_ROOT):
    if entry not in sys.path:
        sys.path.insert(0, entry)

_TEST_DB = os.path.join(tempfile.gettempdir(), "deeptrace_pytest.db")
os.environ.setdefault("DEEPTRACE_DB_PATH", _TEST_DB)


@pytest.fixture(scope="session")
def client():
    """FastAPI test client bound to the throwaway database."""
    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def tmp_file(tmp_path):
    """Factory for a file with known bytes, for hashing and integrity tests."""
    def _make(name: str, payload: bytes) -> str:
        path = tmp_path / name
        path.write_bytes(payload)
        return str(path)
    return _make


def pytest_sessionfinish(session, exitstatus):
    """Remove the throwaway database so runs never inherit prior state."""
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(_TEST_DB + suffix)
        except OSError:
            pass
