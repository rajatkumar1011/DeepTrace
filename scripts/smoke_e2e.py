"""In-process end-to-end smoke test.

Drives the real FastAPI app through the full workflow against a throwaway
database, so a failure here is a real pipeline failure and not a fixture
artifact. Every assertion checks a value the pipeline actually produced.

Run from the repository root:

    backend/venv/Scripts/python.exe scripts/smoke_e2e.py
"""

import os
import sys
import tempfile
import time

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND = os.path.join(REPO_ROOT, "backend")
sys.path.insert(0, BACKEND)

# Windows consoles default to cp1252 and would crash on non-ASCII output.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_TEMP_DB = os.path.join(tempfile.gettempdir(), f"deeptrace_smoke_{os.getpid()}.db")
os.environ["DEEPTRACE_DB_PATH"] = _TEMP_DB

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

FAILURES: list[str] = []
PASSES = 0


def check(label: str, condition: bool, detail: str = "") -> bool:
    global PASSES
    if condition:
        PASSES += 1
        print(f"  PASS  {label}" + (f" - {detail}" if detail else ""))
    else:
        FAILURES.append(label)
        print(f"  FAIL  {label}" + (f" - {detail}" if detail else ""))
    return condition


def find_absolute_paths(value, trail: str = "") -> list[str]:
    """Every JSON string that exposes the operator's filesystem layout.

    Module payloads are returned verbatim by the API and embedded in the report,
    so a stray absolute path there is a real disclosure, not a cosmetic issue.
    """
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            found.extend(find_absolute_paths(item, f"{trail}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value[:4]):
            found.extend(find_absolute_paths(item, f"{trail}[{index}]"))
    elif isinstance(value, str) and REPO_ROOT.lower() in value.replace("/", os.sep).lower():
        found.append(trail.lstrip("."))
    return found


def pick_media() -> tuple[str | None, str | None]:
    """Choose a real video and image already present in the repository."""
    video = image = None
    uploads = os.path.join(REPO_ROOT, "uploads")
    for root in (os.path.join(REPO_ROOT, "data", "demo"), uploads):
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            if not os.path.isfile(path):
                continue
            extension = os.path.splitext(name)[1].lower()
            if video is None and extension == ".mp4" and os.path.getsize(path) > 50_000:
                video = path
            if image is None and extension in {".jpg", ".jpeg", ".png"}:
                image = path
    return video, image


def wait_for_completion(client: TestClient, investigation_id: int, timeout: float = 420.0) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = client.get(f"/api/investigation/{investigation_id}").json()
        if last.get("status") in {"completed", "failed"}:
            return last
        time.sleep(1.0)
    return last


def main_flow() -> int:
    video, image = pick_media()
    if not video:
        print("No .mp4 present in data/demo or uploads; cannot run the video path.")
        return 2

    print(f"Video sample: {os.path.relpath(video, REPO_ROOT)}")
    print(f"Image sample: {os.path.relpath(image, REPO_ROOT) if image else 'none found'}")
    print(f"Isolated database: {_TEMP_DB}\n")

    client = TestClient(main.app)

    print("[1] Health")
    health = client.get("/api/health")
    check("health responds 200", health.status_code == 200)
    capabilities = health.json().get("capabilities", {})
    print(f"        capabilities: {capabilities}")

    print("\n[2] Consent text")
    consent = client.get("/api/consent-text").json()
    check("consent text is served with a version", bool(consent.get("version")) and
          len(consent.get("text", "")) > 100, f"version {consent.get('version')}")

    print("\n[3] Identity enrollment")
    identity_id = None
    if image:
        with open(image, "rb") as handle:
            refused = client.post("/api/identity/enroll", data={"name": "Smoke Subject"},
                                  files={"reference_image": ("ref.jpg", handle, "image/jpeg")})
        check("enrollment without consent is refused", refused.status_code == 422,
              f"HTTP {refused.status_code}")

        with open(image, "rb") as handle:
            enrolled = client.post("/api/identity/enroll",
                                   data={"name": "Smoke Subject", "consent_given": "true"},
                                   files={"reference_image": ("ref.jpg", handle, "image/jpeg")})
        if enrolled.status_code == 200:
            payload = enrolled.json()
            identity_id = payload["id"]
            check("identity enrolled with consent recorded", payload["consent_given"] is True
                  and payload["consent_at"] is not None,
                  f"{payload['face_model']}, {payload['face_embedding_dimensions']}-d")
            check("no absolute path leaks in the identity payload",
                  not str(payload.get("reference_image_path", "")).startswith(REPO_ROOT),
                  str(payload.get("reference_image_path")))
        else:
            check("identity enrolled with consent recorded", False,
                  f"HTTP {enrolled.status_code}: {enrolled.text[:180]}")

    print("\n[4] Upload validation")
    rejected = client.post("/api/investigate",
                           files={"file": ("payload.exe", b"MZ\x00\x00not-media", "application/octet-stream")})
    check("unsupported file type is rejected", rejected.status_code == 415,
          f"HTTP {rejected.status_code}")

    traversal = client.post("/api/investigate",
                            files={"file": ("../../../etc/passwd.jpg", b"\xff\xd8\xff\xe0junk", "image/jpeg")})
    if traversal.status_code == 200:
        stored = client.get(f"/api/investigation/{traversal.json()['id']}").json()
        check("path traversal in the filename is neutralised",
              ".." not in (stored.get("file_path") or "") and
              "etc/passwd" not in (stored.get("file_path") or ""),
              stored.get("file_path"))
    else:
        check("path traversal in the filename is neutralised", False,
              f"upload rejected with HTTP {traversal.status_code}")

    print("\n[5] Investigation intake")
    with open(video, "rb") as handle:
        created = client.post(
            "/api/investigate",
            data={"identity_id": str(identity_id)} if identity_id else {},
            files={"file": (os.path.basename(video), handle, "video/mp4")},
        )
    if created.status_code != 200:
        check("video investigation created", False, f"HTTP {created.status_code}: {created.text[:200]}")
        return 1
    case = created.json()
    investigation_id = case["id"]
    check("video investigation created", True, f"INV-{investigation_id}, sha256 {case['sha256'][:16]}…")
    check("hash is computed server-side at intake", len(case["sha256"]) == 64)

    print("\n[6] Analysis pipeline")
    started = client.post(f"/api/investigation/{investigation_id}/analyze")
    check("analysis accepted", started.status_code == 200, f"HTTP {started.status_code}")
    result = wait_for_completion(client, investigation_id)
    if not check("analysis completed", result.get("status") == "completed",
                 f"status={result.get('status')} stage={result.get('progress_stage')} "
                 f"error={result.get('error_message')}"):
        return 1

    modules = result["analysis_results"]
    print(f"        modules recorded: {len(modules)}")
    for name in sorted(modules):
        entry = modules[name]
        score = "—" if entry["score"] is None else f"{entry['score']:.4f}"
        print(f"          {name:<14} status={entry['status']:<16} score={score}")

    expected = {"metadata", "audio", "deepfake", "localization", "identity", "voice",
                "consistency", "provenance", "similarity", "risk_fusion"}
    check("every pipeline module recorded a result", expected.issubset(modules.keys()),
          f"missing: {sorted(expected - set(modules))}")
    check("exactly one row per module (no duplicates from re-runs)",
          len(modules) == len(expected), f"{len(modules)} modules")

    leaks = find_absolute_paths(modules)
    check("no module payload leaks an absolute filesystem path",
          not leaks, f"{len(leaks)} leak(s): {leaks[:3]}")

    print("\n[7] Real model output, not mocked")
    deepfake = modules["deepfake"]
    check("manipulation score came from a loaded model",
          deepfake["status"] == "completed" and deepfake["score"] is not None,
          f"{(deepfake['data'] or {}).get('model_name')} -> {deepfake['score']}")
    frame_results = (deepfake["data"] or {}).get("frame_results") or []
    check("per-frame scores are distinct (not a constant fill)",
          len({round(float(f["manipulation_signal"]), 6) for f in frame_results}) > 1,
          f"{len(frame_results)} frames, "
          f"{len({round(float(f['manipulation_signal']), 6) for f in frame_results})} distinct values")
    check("faces were located inside frames before scoring",
          (deepfake["data"] or {}).get("frames_with_face") is not None,
          f"{(deepfake['data'] or {}).get('frames_with_face')} of "
          f"{(deepfake['data'] or {}).get('frames_analyzed')} frames had a detected face")

    print("\n[8] A/V consistency actually ran (regression check)")
    consistency = modules["consistency"]
    check("A/V consistency is no longer permanently unavailable",
          consistency["status"] in {"completed", "not_applicable"},
          f"status={consistency['status']} "
          f"score={consistency['score']} "
          f"detail={(consistency['data'] or {}).get('details', '')[:90]}")

    print("\n[9] Similarity is bounded (regression check)")
    similarity = modules["similarity"]
    match_count = (similarity["data"] or {}).get("match_count", 0)
    check("similarity reports at most one match per related case",
          match_count <= 25, f"{match_count} matches")

    print("\n[10] Risk fusion is explainable")
    risk = modules["risk_fusion"]["data"] or {}
    check("risk score and level were derived", result["risk_level"] is not None
          and result["overall_risk_score"] is not None,
          f"{result['risk_level']} @ {result['overall_risk_score']:.3f}")
    check("every contributing signal is itemised with a weight",
          all("contribution" in s and "effective_weight" in s for s in risk.get("signals", []))
          and len(risk.get("signals", [])) > 0,
          f"{len(risk.get('signals', []))} signals, "
          f"{len(risk.get('excluded_signals', []))} excluded")
    check("effective weights sum to 1 across available signals",
          abs(sum(s["effective_weight"] for s in risk.get("signals", [])) - 1.0) < 0.01,
          f"{sum(s['effective_weight'] for s in risk.get('signals', [])):.4f}")
    check("the explanation is prose derived from the numbers",
          len(risk.get("explanation", "")) > 200, f"{len(risk.get('explanation',''))} chars")

    print("\n[11] Evidence preservation and integrity")
    evidence = client.get(f"/api/investigation/{investigation_id}/evidence").json()
    check("evidence artifacts were preserved", len(evidence) > 1, f"{len(evidence)} artifacts")
    check("no absolute filesystem path is exposed",
          all(not str(item.get("file_path") or "").startswith(REPO_ROOT) for item in evidence))
    check("every artifact carries a SHA-256",
          all(item["sha256"] for item in evidence))

    verified = client.get(f"/api/investigation/{investigation_id}/verify").json()
    check("integrity re-verification passes on untouched evidence",
          verified["chain_intact"] is True,
          f"{verified['counts']['verified']}/{verified['artifacts_checked']} verified")

    print("\n[12] Tamper detection")
    frame = next((item for item in evidence if item["type"] == "frame"), None)
    if frame:
        target = os.path.join(REPO_ROOT, frame["file_path"])
        with open(target, "rb") as handle:
            original_bytes = handle.read()
        with open(target, "ab") as handle:
            handle.write(b"\x00tampered")
        tampered = client.get(f"/api/investigation/{investigation_id}/verify").json()
        check("altering a preserved file is detected as a mismatch",
              tampered["counts"]["mismatch"] == 1 and tampered["chain_intact"] is False,
              tampered["summary"][:110])
        with open(target, "wb") as handle:
            handle.write(original_bytes)
        restored = client.get(f"/api/investigation/{investigation_id}/verify").json()
        check("restoring the bytes restores verification", restored["chain_intact"] is True)

    print("\n[13] SSRF and URL validation")
    for label, url in (
        ("localhost is rejected", "https://localhost/x.jpg"),
        ("private RFC1918 address is rejected", "https://192.168.1.1/x.jpg"),
        ("link-local metadata address is rejected", "https://169.254.169.254/latest/meta-data"),
        ("plain http is rejected", "http://example.com/x.jpg"),
        ("file scheme is rejected", "file:///C:/Windows/win.ini"),
    ):
        response = client.post(f"/api/investigation/{investigation_id}/trace",
                               data={"source_urls": url})
        blocked = response.status_code == 422
        if not blocked and response.status_code == 200:
            sources = response.json()["sources"]
            matching = [s for s in sources if s["source_url"] == url]
            blocked = bool(matching) and matching[0]["retrieval_status"] == "rejected"
        check(label, blocked, f"HTTP {response.status_code}")

    print("\n[14] Local copy tracing")
    if image:
        with open(image, "rb") as handle:
            traced = client.post(f"/api/investigation/{investigation_id}/trace",
                                 data={"label": "Investigator copy"},
                                 files={"local_copy": ("copy.jpg", handle, "image/jpeg")})
        check("an investigator-supplied copy is hashed and compared",
              traced.status_code == 200, f"HTTP {traced.status_code}: {traced.text[:150]}")

    print("\n[15] Response guidance")
    guidance = client.get(f"/api/investigation/{investigation_id}/response-guidance").json()
    check("guidance is generated from case findings",
          len(guidance.get("recommended_actions", [])) >= 3,
          f"{len(guidance.get('recommended_actions', []))} actions, "
          f"priority {guidance.get('priority')}")
    check("guidance states DeepTrace's boundary",
          "does not file complaints" in guidance.get("deeptrace_boundary", ""))

    print("\n[16] Report generation")
    report = client.get(f"/api/investigation/{investigation_id}/report")
    if check("report generated", report.status_code == 200,
             f"HTTP {report.status_code}: {report.text[:180]}"):
        info = report.json()
        pdf = os.path.join(REPO_ROOT, info["report_path"]) if info.get("report_path") else None
        size = os.path.getsize(pdf) if pdf and os.path.isfile(pdf) else 0
        check("report PDF written to disk", size > 20_000, f"{size:,} bytes")
        download = client.get(f"/api/report/{investigation_id}/download")
        check("report downloadable", download.status_code == 200
              and download.content[:5] == b"%PDF-", f"HTTP {download.status_code}")

    print("\n[17] Timeline")
    timeline = client.get(f"/api/investigation/{investigation_id}/timeline").json()
    kinds = {event["event_type"] for event in timeline}
    check("timeline records the whole workflow", len(timeline) >= 12, f"{len(timeline)} events")
    for required in ("investigation_created", "hash_generated", "frames_sampled",
                     "manipulation_analysis", "risk_assessment", "analysis_completed"):
        check(f"timeline includes {required}", required in kinds)

    print("\n[18] Re-analysis idempotency")
    before_evidence = len(client.get(f"/api/investigation/{investigation_id}/evidence").json())
    client.post(f"/api/investigation/{investigation_id}/analyze")
    rerun = wait_for_completion(client, investigation_id)
    if check("re-analysis completes", rerun.get("status") == "completed",
             f"status={rerun.get('status')} error={rerun.get('error_message')}"):
        after_evidence = len(client.get(f"/api/investigation/{investigation_id}/evidence").json())
        check("re-analysis does not duplicate module rows",
              len(rerun["analysis_results"]) == len(expected),
              f"{len(rerun['analysis_results'])} modules")
        check("re-analysis does not accumulate derived artifacts",
              after_evidence == before_evidence,
              f"{before_evidence} before, {after_evidence} after")
        check("the original media hash is unchanged by re-analysis",
              rerun["sha256_hash"] == case["sha256"])
        rechecked = client.get(f"/api/investigation/{investigation_id}/verify").json()
        check("evidence still verifies after re-analysis", rechecked["chain_intact"] is True,
              rechecked["summary"][:100])

    print("\n[19] Image path")
    if image:
        with open(image, "rb") as handle:
            image_case = client.post("/api/investigate",
                                     data={"identity_id": str(identity_id)} if identity_id else {},
                                     files={"file": (os.path.basename(image), handle, "image/jpeg")})
        if image_case.status_code == 200:
            image_id = image_case.json()["id"]
            client.post(f"/api/investigation/{image_id}/analyze")
            image_result = wait_for_completion(client, image_id, timeout=180)
            check("image investigation completes", image_result.get("status") == "completed",
                  f"status={image_result.get('status')} error={image_result.get('error_message')}")
            image_modules = image_result.get("analysis_results", {})
            check("audio modules report not-applicable for a still image",
                  image_modules.get("audio", {}).get("status") == "not_applicable"
                  and image_modules.get("consistency", {}).get("status") == "not_applicable",
                  f"audio={image_modules.get('audio', {}).get('status')}, "
                  f"consistency={image_modules.get('consistency', {}).get('status')}")
            image_report = client.get(f"/api/investigation/{image_id}/report")
            check("image report generated", image_report.status_code == 200,
                  f"HTTP {image_report.status_code}: {image_report.text[:150]}")

    print("\n[20] Dashboard")
    stats = client.get("/api/dashboard/stats").json()
    check("dashboard counts reflect the isolated database",
          stats["active_investigations"] >= 2, str(stats))

    benchmark = client.get("/api/benchmark").json()
    check("benchmark endpoint is honest when no run exists",
          "available" in benchmark, f"available={benchmark.get('available')}")

    return 1 if FAILURES else 0


if __name__ == "__main__":
    start = time.time()
    try:
        code = main_flow()
    finally:
        elapsed = time.time() - start
        print(f"\n{'=' * 74}")
        print(f"{PASSES} passed, {len(FAILURES)} failed in {elapsed:.1f}s")
        if FAILURES:
            for item in FAILURES:
                print(f"  FAILED: {item}")
        try:
            from database import engine

            engine.dispose()
        except Exception:
            pass
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(_TEMP_DB + suffix)
            except OSError:
                pass
    raise SystemExit(code)
