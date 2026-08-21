import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
UPLOAD_DIR = os.path.join(PROJECT_ROOT, "uploads")
EVIDENCE_DIR = os.path.join(PROJECT_ROOT, "evidence")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
REPORTS_DIR = os.path.join(DATA_DIR, "reports")
DEMO_DIR = os.path.join(DATA_DIR, "demo")


def ensure_runtime_dirs():
    os.makedirs(os.path.join(UPLOAD_DIR, "identities"), exist_ok=True)
    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    os.makedirs(REPORTS_DIR, exist_ok=True)
    os.makedirs(DEMO_DIR, exist_ok=True)
