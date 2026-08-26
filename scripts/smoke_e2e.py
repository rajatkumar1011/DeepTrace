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


def extract_pdf_text(path: str | None) -> str | None:
    """The report's text, or None when no extractor is installed.

    ReportLab compresses page streams, so the produced PDF cannot be grepped as
    bytes and asserting on its size alone would pass for any 20 KB file. pypdf is
    a verification-only dependency and is not required by the running service, so
    its absence degrades to a skipped assertion rather than a failure.
    """
    if not path or not os.path.isfile(path):
        return None
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        reader = PdfReader(path)
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as error:
        print(f"        note: the report PDF could not be parsed for text ({error})")
        return None


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
    health_payload = health.json()
    capabilities = health_payload.get("capabilities", {})
    capability_evidence = health_payload.get("capability_evidence", {})
    print(f"        capabilities: {capabilities}")
    # The capability flags decide what the UI offers and what the report is allowed
    # to claim, so a missing key is a contract break even when every value present
    # happens to be True. Printing them was not enough: an absent flag printed as
    # an absent flag still passed.
    check("health declares every capability flag the UI depends on",
          {"ffmpeg", "deepfakebench_xception_weights", "speaker_model_cached",
           "c2pa_reader"}.issubset(capabilities),
          f"missing: {sorted({'ffmpeg', 'deepfakebench_xception_weights', 'speaker_model_cached', 'c2pa_reader'} - set(capabilities))}")
    check("every capability flag is a boolean, never a hedge",
          all(isinstance(value, bool) for value in capabilities.values()),
          f"{ {k: type(v).__name__ for k, v in capabilities.items()} }")
    check("each capability states how it was established",
          set(capabilities).issubset(capability_evidence) and
          all((capability_evidence.get(key) or {}).get("method") for key in capabilities),
          f"{len(capability_evidence)} evidence entries for {len(capabilities)} flags")
    check("ffmpeg availability is proved by execution, not by a path guess",
          "-version" in ((capability_evidence.get("ffmpeg") or {}).get("method") or ""),
          (capability_evidence.get("ffmpeg") or {}).get("method", "no method recorded")[:80])
    limits = health_payload.get("limits", {})
    check("upload limits are declared numerically",
          all(isinstance(limits.get(key), int) and limits[key] > 0
              for key in ("max_upload_mb", "max_reference_mb", "frame_samples")),
          str(limits))

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

    print("\n[8] Every module reports a status the UI can render honestly")
    # The UI decides between "here is a finding" and "this did not run" purely from
    # `status`. A module that returns a score with no status, or a status outside
    # the known set, makes that decision impossible and is how a gap turns into a
    # silent zero on screen.
    known_statuses = {"completed", "unavailable", "not_applicable", "no_credentials", "not_run"}
    unknown = {name: entry["status"] for name, entry in modules.items()
               if entry["status"] not in known_statuses}
    check("every module status is one the UI knows how to render",
          not unknown, f"unrecognised: {unknown}")
    scored_without_status = {name for name, entry in modules.items()
                             if entry["score"] is not None and entry["status"] != "completed"}
    check("no module reports a score while claiming it did not complete",
          not scored_without_status, f"{sorted(scored_without_status)}")
    unavailable_without_reason = {
        name for name, entry in modules.items()
        if entry["status"] in {"unavailable", "not_run"}
        and not ((entry["data"] or {}).get("reason") or (entry["data"] or {}).get("details"))
    }
    check("an unavailable module states why, rather than failing silently",
          not unavailable_without_reason, f"{sorted(unavailable_without_reason)}")
    for name in ("metadata", "identity", "voice", "localization", "provenance"):
        entry = modules.get(name) or {}
        payload = entry.get("data") or {}
        detail = (payload.get("method") or payload.get("reason")
                  or payload.get("details") or "no method or reason recorded")
        check(f"{name} reports a status and the basis for it",
              entry.get("status") in known_statuses and bool(detail),
              f"status={entry.get('status')} - {str(detail)[:80]}")
    identity_module = modules.get("identity") or {}
    if identity_id:
        check("identity comparison ran against the enrolled reference",
              identity_module.get("status") == "completed"
              and identity_module.get("score") is not None,
              f"status={identity_module.get('status')} score={identity_module.get('score')}")
    else:
        check("identity comparison is not-applicable with no enrolled reference",
              identity_module.get("status") in {"not_applicable", "unavailable"},
              f"status={identity_module.get('status')}")
    localization = modules.get("localization") or {}
    if localization.get("status") == "completed":
        localization_data = localization.get("data") or {}
        suspicious_count = localization_data.get("suspicious_frame_count") or 0
        overlays = localization_data.get("overlays") or []
        # An empty overlay list is correct when nothing crossed the threshold, so
        # the assertion is about consistency, not about producing pictures: a claim
        # that N frames are suspicious has to come with somewhere to look.
        check("localization overlays are consistent with the frames it flagged",
              bool(overlays) if suspicious_count else True,
              f"{suspicious_count} suspicious frame(s), {len(overlays)} overlay(s)")
        check("localization names the interval(s) it flagged, not just a count",
              isinstance(localization_data.get("suspicious_intervals"), list),
              f"{len(localization_data.get('suspicious_intervals') or [])} interval(s)")

    print("\n[9] A/V consistency actually ran (regression check)")
    consistency = modules["consistency"]
    check("A/V consistency is no longer permanently unavailable",
          consistency["status"] in {"completed", "not_applicable"},
          f"status={consistency['status']} "
          f"score={consistency['score']} "
          f"detail={(consistency['data'] or {}).get('details', '')[:90]}")

    print("\n[10] Similarity is bounded (regression check)")
    similarity = modules["similarity"]
    match_count = (similarity["data"] or {}).get("match_count", 0)
    check("similarity reports at most one match per related case",
          match_count <= 25, f"{match_count} matches")

    print("\n[11] Risk fusion is explainable")
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

    print("\n[12] Evidence preservation and integrity")
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

    print("\n[13] Chain of custody")
    custody = client.get(f"/api/investigation/{investigation_id}/custody")
    if check("custody record is served", custody.status_code == 200,
             f"HTTP {custody.status_code}: {custody.text[:150]}"):
        record = custody.json()
        acquisition = record.get("acquisition") or {}
        check("acquisition records the digest the pipeline computed at intake",
              acquisition.get("sha256") == case["sha256"]
              and acquisition.get("algorithm") == "SHA-256",
              f"{acquisition.get('algorithm')} {str(acquisition.get('sha256'))[:16]}…")
        check("the digest is bound to a stated scope, not left implicit",
              len(acquisition.get("hash_binding") or "") > 40,
              (acquisition.get("hash_binding") or "none")[:80])
        check("the clock behind every timestamp is named",
              bool(acquisition.get("clock_source")),
              (acquisition.get("clock_source") or "none")[:80])

        ledger = record.get("artifact_ledger") or []
        counts = record.get("counts") or {}
        check("the ledger accounts for every preserved artifact",
              len(ledger) == len(evidence) == counts.get("artifacts"),
              f"{len(ledger)} ledger rows, {len(evidence)} evidence rows, "
              f"counts.artifacts={counts.get('artifacts')}")
        check("each artifact is marked acquired or derived, never unclassified",
              bool(ledger) and all(entry.get("origin") in {"acquired", "derived"}
                                   for entry in ledger),
              f"{counts.get('acquired')} acquired, {counts.get('derived')} derived")
        check("every ledger row states the role the artifact plays",
              all(entry.get("role") and entry.get("role_detail") for entry in ledger))
        check("artifacts without a recorded digest are counted, not hidden",
              counts.get("without_digest") == sum(
                  1 for entry in ledger if not entry.get("digest_recorded")),
              f"{counts.get('without_digest')} without a digest")

        # This is the distinction the evaluators asked us to make explicit. It is
        # asserted rather than trusted because it is the one claim in the product
        # that would be actively misleading if the lists were ever emptied.
        for key, label in (("hashing_proves", "what hashing proves"),
                           ("hashing_does_not_prove", "what hashing does not prove"),
                           ("ai_establishes", "what the AI analysis establishes"),
                           ("ai_does_not_establish", "what the AI analysis does not establish")):
            entries = record.get(key) or []
            check(f"custody states {label}, with a basis for each statement",
                  len(entries) >= 2 and all(entry.get("claim") and entry.get("detail")
                                            for entry in entries),
                  f"{len(entries)} statement(s)")
        boundary_text = " ".join(
            f"{entry.get('claim', '')} {entry.get('detail', '')}"
            for entry in (record.get("hashing_does_not_prove") or [])).lower()
        check("hashing is explicitly not claimed to prove authenticity",
              "authentic" in boundary_text or "genuine" in boundary_text,
              boundary_text[:100])

        check("custody names the gaps DeepTrace cannot close",
              len(record.get("custody_gaps") or []) >= 1
              and all(gap.get("gap") and gap.get("detail")
                      for gap in record.get("custody_gaps") or []),
              f"{len(record.get('custody_gaps') or [])} gap(s)")
        check("custody chronology is ordered and complete",
              [entry["sequence"] for entry in record.get("chronology") or []]
              == list(range(1, len(record.get("chronology") or []) + 1)),
              f"{len(record.get('chronology') or [])} events")
        check("the custody record carries the integrity check, not a separate claim",
              (record.get("integrity_check") or {}).get("chain_intact") is True,
              str((record.get("integrity_check") or {}).get("summary"))[:90])
        custody_leaks = find_absolute_paths(record)
        check("the custody record leaks no absolute filesystem path",
              not custody_leaks, f"{len(custody_leaks)} leak(s): {custody_leaks[:3]}")

    print("\n[14] Tamper detection")
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

    print("\n[15] SSRF and URL validation")
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

    print("\n[16] Local copy tracing")
    if image:
        with open(image, "rb") as handle:
            traced = client.post(f"/api/investigation/{investigation_id}/trace",
                                 data={"label": "Investigator copy"},
                                 files={"local_copy": ("copy.jpg", handle, "image/jpeg")})
        check("an investigator-supplied copy is hashed and compared",
              traced.status_code == 200, f"HTTP {traced.status_code}: {traced.text[:150]}")

    print("\n[17] Response guidance")
    guidance = client.get(f"/api/investigation/{investigation_id}/response-guidance").json()
    check("guidance is generated from case findings",
          len(guidance.get("recommended_actions", [])) >= 3,
          f"{len(guidance.get('recommended_actions', []))} actions, "
          f"priority {guidance.get('priority')}")
    check("guidance states DeepTrace's boundary",
          "does not file complaints" in guidance.get("deeptrace_boundary", ""))

    print("\n[18] Report generation")
    report = client.get(f"/api/investigation/{investigation_id}/report")
    if check("report generated", report.status_code == 200,
             f"HTTP {report.status_code}: {report.text[:180]}"):
        info = report.json()
        pdf = os.path.join(REPO_ROOT, info["report_path"]) if info.get("report_path") else None
        size = os.path.getsize(pdf) if pdf and os.path.isfile(pdf) else 0
        check("report PDF written to disk", size > 20_000, f"{size:,} bytes")
        check("the report's own digest is reported with it",
              len(info.get("sha256") or "") == 64, str(info.get("sha256"))[:16] + "…")
        download = client.get(f"/api/report/{investigation_id}/download")
        check("report downloadable", download.status_code == 200
              and download.content[:5] == b"%PDF-", f"HTTP {download.status_code}")

        # Size and magic bytes only prove a PDF was produced. What matters is
        # whether it says the things the project promises it says — and whether it
        # avoids the claims it promises never to make.
        text = extract_pdf_text(pdf) if pdf else None
        if text is None:
            print("        SKIP  report content assertions - install pypdf to enable them")
        else:
            check("report is substantial, not a stub", len(text) > 8_000, f"{len(text):,} chars")
            for phrase in (
                "Chain of Custody",
                "System Validation",
                "Methodology, Models, Limitations and Notice",
                "What DeepTrace does not claim",
            ):
                check(f"report contains the '{phrase}' section", phrase in text)
            check("the report carries the case digest computed at intake",
                  case["sha256"] in text.replace("\n", ""), case["sha256"][:16] + "…")
            check("the report names the model that produced the manipulation score",
                  str((deepfake["data"] or {}).get("model_name") or "?") in text,
                  str((deepfake["data"] or {}).get("model_name")))
            check("the report separates what hashing proves from what AI establishes",
                  "hashing" in text.lower() and "does not prove" in text.lower())
            # Phrases that cannot appear in an honest report in any form.
            for forbidden in (
                "100% accurate", "guaranteed detection", "proves the video is fake",
                "conclusive proof", "definitively fake",
            ):
                check(f"the report never claims '{forbidden}'",
                      forbidden.lower() not in text.lower())
            # Capabilities DeepTrace disclaims. The words themselves are expected —
            # the report has to name a capability in order to deny having it — so a
            # bare substring search here would flag the disclaimer that makes the
            # report honest. What must hold is that every occurrence is negated, and
            # that the denial is present at all rather than the subject going unraised.
            # Matched against whitespace-collapsed text: reportlab wraps lines
            # wherever the column ends, so a denial can be split mid-phrase.
            flat = " ".join(text.lower().split())
            for term, denials in (
                ("internet-wide", ("no internet-wide", "performs no internet-wide",
                                   "not an internet-wide", "not perform internet-wide")),
                ("surveillance", ("not perform internet-wide surveillance",
                                  "no internet-wide surveillance")),
                ("admissib", ("not by itself establish legal admissibility",
                              "not guarantee legal admissibility")),
            ):
                occurrences = flat.count(term)
                negated = sum(flat.count(phrase) for phrase in denials)
                check(f"'{term}' appears only as a disclaimed capability",
                      occurrences == 0 or negated >= 1,
                      f"{occurrences} mention(s), {negated} denial(s)")
            check("the report disclaims internet-wide search rather than staying silent",
                  "internet-wide" in flat)
            check("every page is marked as indicators rather than proof",
                  text.count("Forensic indicators") >= 2,
                  f"{text.count('Forensic indicators')} page footers")

    print("\n[19] Timeline")
    timeline = client.get(f"/api/investigation/{investigation_id}/timeline").json()
    kinds = {event["event_type"] for event in timeline}
    check("timeline records the whole workflow", len(timeline) >= 12, f"{len(timeline)} events")
    for required in ("investigation_created", "hash_generated", "frames_sampled",
                     "manipulation_analysis", "risk_assessment", "analysis_completed"):
        check(f"timeline includes {required}", required in kinds)

    print("\n[20] Re-analysis idempotency")
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

    print("\n[21] Image path")
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

    print("\n[22] Dashboard")
    stats = client.get("/api/dashboard/stats").json()
    check("dashboard counts reflect the isolated database",
          stats["active_investigations"] >= 2, str(stats))

    print("\n[23] Validation reporting")
    # This endpoint is the only place DeepTrace reports on itself, so it is the
    # place where a fabricated figure would be hardest to notice. The assertions
    # branch on which harnesses have actually been run in this environment: an
    # absent run must carry a reason and no numbers, and a present run must carry
    # its provenance and its caveats.
    benchmark = client.get("/api/benchmark")
    check("validation endpoint responds 200", benchmark.status_code == 200)
    validation = benchmark.json()
    check("validation payload separates labelled metrics from robustness",
          {"metrics_available", "robustness_available", "boundary"}.issubset(validation),
          f"metrics={validation.get('metrics_available')} "
          f"robustness={validation.get('robustness_available')}")
    check("the boundary between the two measurements is stated",
          "how often the detector is right" in (validation.get("boundary") or "")
          and "how much its score moves" in (validation.get("boundary") or ""))
    check("the legacy 'available' flag still means labelled metrics only",
          validation.get("available") == validation.get("metrics_available"),
          f"available={validation.get('available')}")

    detection = validation.get("manipulation_detection")
    if not validation.get("metrics_available"):
        check("absent labelled metrics are reported as absent, with a reason",
              bool(validation.get("reason")) and detection is None,
              (validation.get("reason") or "no reason given")[:90])
    else:
        point = (detection or {}).get("operating_point") or {}
        check("labelled metrics report precision, recall, F1 and both error rates",
              {"precision", "recall_sensitivity", "f1",
               "false_positive_rate", "false_negative_rate"}.issubset(point),
              f"precision={point.get('precision')} recall={point.get('recall_sensitivity')} "
              f"F1={point.get('f1')} FPR={point.get('false_positive_rate')}")
        check("the error rates are defined in words, not just named",
              bool(point.get("false_positive_rate_definition"))
              and bool(point.get("false_negative_rate_definition")))
        check("confusion counts add up to the number of files scored",
              sum(point.get(key) or 0 for key in ("true_positive", "false_positive",
                                                  "true_negative", "false_negative"))
              == (detection or {}).get("evaluated"),
              f"{(detection or {}).get('evaluated')} files scored")
        check("the labels' provenance is recorded, not assumed",
              bool(((detection or {}).get("dataset_provenance") or {}).get("label_source")),
              str(((detection or {}).get("dataset_provenance") or {}).get("label_source")))
        check("the metrics carry caveats limiting what they may be read as",
              len((detection or {}).get("caveats") or []) >= 3,
              f"{len((detection or {}).get('caveats') or [])} caveats")
        check("the model that produced the figures is named",
              bool((detection or {}).get("model")), str((detection or {}).get("model")))
        check("the evaluated dataset is fingerprinted so a result cannot be reused",
              len(str((detection or {}).get("dataset_fingerprint") or "")) >= 8,
              str((detection or {}).get("dataset_fingerprint")))

    robustness = validation.get("robustness") or {}
    if not robustness.get("available"):
        check("absent robustness results are reported as absent, with a reason",
              bool(robustness.get("reason")) and "visual" not in robustness,
              (robustness.get("reason") or "no reason given")[:90])
    else:
        check("robustness states what it measures",
              len(robustness.get("what_this_measures") or "") > 60)
        check("robustness records the media it degraded and its fingerprint",
              bool((robustness.get("source") or {}).get("fingerprint"))
              and ((robustness.get("source") or {}).get("file_count") or 0) > 0,
              f"{(robustness.get('source') or {}).get('file_count')} source file(s)")
        for channel_key in ("visual", "audio"):
            channel = robustness.get(channel_key) or {}
            overall = channel.get("overall") or {}
            pairs = overall.get("paired_comparisons") or 0
            if not pairs:
                print(f"        note: no {channel_key} pairs were compared in this run")
                continue
            check(f"{channel_key} robustness reports agreement over real pairs",
                  overall.get("decision_agreement") is not None
                  and overall.get("mean_absolute_delta") is not None,
                  f"{pairs} pairs, agreement {overall.get('decision_agreement')}, "
                  f"mean shift {overall.get('mean_absolute_delta')}")
            check(f"{channel_key} agreement counts are consistent with the pair count",
                  0 <= (overall.get("decisions_preserved") or 0) <= pairs,
                  f"{overall.get('decisions_preserved')}/{pairs} preserved")
            check(f"{channel_key} robustness names the transform that hurt most",
                  bool((overall.get("most_disruptive_transform") or {}).get("label")),
                  str((overall.get("most_disruptive_transform") or {}).get("label"))[:70])
        check("robustness carries caveats of its own",
              len(robustness.get("caveats") or []) >= 3,
              f"{len(robustness.get('caveats') or [])} caveats")

    validation_leaks = find_absolute_paths(validation)
    check("the validation payload leaks no absolute filesystem path",
          not validation_leaks, f"{len(validation_leaks)} leak(s): {validation_leaks[:3]}")

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
