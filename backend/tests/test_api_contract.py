"""API contract and rejection paths.

Scope note: these exercise validation, error handling and response hygiene — the
paths that must hold regardless of which models are installed. They deliberately
avoid the model-backed happy path, which writes to the evidence store and is
covered end-to-end by ``scripts/smoke_e2e.py`` against a live server.
"""

import io
import json

import pytest

from paths import PROJECT_ROOT


def payload_text(response):
    return json.dumps(response.json())


# ── Read-only endpoints ──────────────────────────────────────────────────────

def test_health_reports_capabilities_and_limits(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert "limits" in body
    assert body["limits"]["max_upload_mb"] > 0
    assert body["limits"]["frame_samples"] > 0


def test_consent_text_is_served_with_a_version(client):
    response = client.get("/api/consent-text")
    assert response.status_code == 200
    body = response.json()
    assert body["version"], "consent text must carry a version so enrolments are auditable"
    assert len(body["text"]) > 50


def test_benchmark_reports_unavailable_rather_than_shipping_figures(client):
    """§34: no dataset in this environment means no metrics, with a stated reason."""
    response = client.get("/api/benchmark")
    assert response.status_code == 200
    body = response.json()
    if body.get("available"):
        pytest.skip("A benchmark has been run in this environment; nothing to assert here.")
    assert body["available"] is False
    assert body["reason"].strip()
    assert "does not ship pre-computed accuracy figures" in body["reason"]


def test_dashboard_stats_are_served(client):
    assert client.get("/api/dashboard/stats").status_code == 200


def test_demo_assets_are_listed_as_demo_input(client):
    """Demo media is permitted only when clearly identified as such (§34)."""
    response = client.get("/api/demo/assets")
    assert response.status_code == 200
    for asset in response.json()["assets"]:
        assert asset["url"].startswith("/")
        assert not asset["url"].startswith("//")


# ── Consent enforcement ──────────────────────────────────────────────────────

def image_upload():
    return {"reference_image": ("face.jpg", io.BytesIO(b"\xff\xd8\xff\xe0not-a-real-jpeg"), "image/jpeg")}


@pytest.mark.parametrize("consent", ["false", "", "no", "0", "maybe"])
def test_enrollment_is_refused_without_consent(client, consent):
    response = client.post("/api/identity/enroll",
                           data={"name": "Consent Test", "consent_given": consent},
                           files=image_upload())
    assert response.status_code == 422
    assert "onsent" in payload_text(response)


def test_enrollment_requires_a_name(client):
    response = client.post("/api/identity/enroll",
                           data={"name": "   ", "consent_given": "true"},
                           files=image_upload())
    assert response.status_code == 422


def test_enrollment_bounds_the_name_length(client):
    response = client.post("/api/identity/enroll",
                           data={"name": "n" * 500, "consent_given": "true"},
                           files=image_upload())
    assert response.status_code == 422


# ── Upload validation ────────────────────────────────────────────────────────

@pytest.mark.parametrize("filename,content_type", [
    ("payload.txt", "text/plain"),
    ("script.exe", "application/octet-stream"),
    ("archive.zip", "application/zip"),
    ("page.html", "text/html"),
    ("shell.sh", "application/x-sh"),
    ("noextension", "application/octet-stream"),
])
def test_unsupported_media_types_are_refused(client, filename, content_type):
    response = client.post("/api/investigate",
                           files={"file": (filename, io.BytesIO(b"payload"), content_type)})
    assert response.status_code == 415
    assert "Unsupported media type" in payload_text(response)


def test_investigation_against_a_nonexistent_identity_is_refused(client):
    response = client.post("/api/investigate",
                           files={"file": ("clip.mp4", io.BytesIO(b"\x00" * 64), "video/mp4")},
                           data={"identity_id": "999999"})
    assert response.status_code == 422
    assert "no longer exists" in payload_text(response)


# ── Unknown resources ────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "/api/investigation/999999",
    "/api/investigation/999999/timeline",
    "/api/investigation/999999/evidence",
    "/api/investigation/999999/verify",
    "/api/investigation/999999/response-guidance",
    "/api/investigation/999999/similarity",
    "/api/identity/999999",
    "/api/report/999999/download",
])
def test_unknown_resources_return_404_without_a_stack_trace(client, path):
    response = client.get(path)
    assert response.status_code == 404
    body = response.text
    assert "Traceback" not in body
    assert "sqlalchemy" not in body.lower()


def test_malformed_path_parameters_are_rejected_cleanly(client):
    response = client.get("/api/investigation/not-a-number")
    assert response.status_code == 422
    assert "Traceback" not in response.text


# ── Response hygiene (§24: never expose internal filesystem paths) ────────────

@pytest.mark.parametrize("path", [
    "/api/health",
    "/api/benchmark",
    "/api/demo/assets",
    "/api/investigations",
    "/api/identities",
    "/api/dashboard/stats",
])
def test_responses_never_leak_absolute_filesystem_paths(client, path):
    body = payload_text(client.get(path))
    assert PROJECT_ROOT.replace("\\", "\\\\") not in body
    assert PROJECT_ROOT.replace("\\", "/") not in body
    assert "C:\\\\Users" not in body
    assert "/home/" not in body


def test_error_responses_do_not_disclose_internals(client):
    body = client.post("/api/investigate",
                       files={"file": ("x.txt", io.BytesIO(b"x"), "text/plain")}).text
    for marker in ("Traceback", "site-packages", PROJECT_ROOT.replace("\\", "/")):
        assert marker not in body
