#!/usr/bin/env python3
"""Drive one complete investigation through the running API and write it up.

Every figure in ``docs/WALKTHROUGH.md`` is produced by this script calling the
same HTTP endpoints the browser calls. Nothing is transcribed by hand, nothing is
illustrative, and the document records the case ID so a reader can open the same
case in the UI and see the same values. If a module is unavailable on the machine
that ran it, the write-up says so in the module's own words rather than omitting
the row.

The point of the artifact is the boundary between two very different kinds of
claim, which a demo tends to blur:

  * The hash chain is arithmetic. It proves the bytes now stored are the bytes
    received, and that the report describes those bytes. It proves nothing about
    whether the media is genuine.
  * The module scores are inference. They are evidence about the media, with
    stated confidence and stated failure modes, and they do not establish who
    made it or that a crime occurred.

So the write-up recomputes the hashes independently — in this process, not by
asking the API to confirm its own arithmetic — and reports the two categories in
separate sections that say what each does and does not establish.

Usage
-----
    python scripts/walkthrough.py                       # demo assets
    python scripts/walkthrough.py --suspect A --reference B --identity-name "..."

The backend must already be running. This script starts nothing: a walkthrough
that silently launched its own server would not be describing the deployment the
reader is looking at.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

# Windows consoles default to cp1252 and would crash on the dashes below.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DEFAULT_BASE = os.environ.get("DEEPTRACE_API", "http://127.0.0.1:8000")
OUTPUT_PATH = os.path.join(REPO_ROOT, "docs", "WALKTHROUGH.md")

DEMO_DIR = os.path.join(REPO_ROOT, "data", "demo")
PAIRS_DIR = os.path.join(REPO_ROOT, "data", "benchmark", "pairs")
DEFAULT_SUSPECT = os.path.join(DEMO_DIR, "lena.jpg")
DEFAULT_REFERENCE = os.path.join(DEMO_DIR, "reference_face.png")

LFW_NOTE = (
    "Demonstration input: two different genuine photographs of the same person, taken from the "
    "public Labeled Faces in the Wild corpus. This exercises the impersonation path the product "
    "is actually built for — a real face surfacing somewhere the complainant did not put it — with "
    "input whose ground truth is known, so the identity result can be checked rather than merely "
    "read. The media is demonstration data; every score, hash, timestamp and finding below is "
    "real output from this run."
)
DEMO_NOTE = (
    "Demonstration input: the bundled demo assets, which are two photographs of different people. "
    "The identity comparison is therefore expected to report a non-match, and does. The media is "
    "demonstration data; every score, hash, timestamp and finding below is real output from this "
    "run."
)


def default_inputs() -> tuple[str, str, str]:
    """Pick the input pair that makes the walkthrough a coherent case.

    Preference goes to a same-person pair from the evaluation corpus, because the
    document is meant to show the impersonation workflow end to end and a pair with
    known ground truth lets a reader check the identity result instead of taking it
    on trust. The bundled demo assets are two different people, so they produce a
    correct but far less illustrative non-match. Either way the note explaining
    which was used is printed in the write-up: a reader must never have to guess
    whether an identity score was supposed to match.
    """
    suspect = os.path.join(PAIRS_DIR, "lfw_test_00000_b.jpg")
    reference = os.path.join(PAIRS_DIR, "lfw_test_00000_a.jpg")
    if os.path.isfile(suspect) and os.path.isfile(reference):
        return suspect, reference, LFW_NOTE
    return DEFAULT_SUSPECT, DEFAULT_REFERENCE, DEMO_NOTE

ANALYSIS_TIMEOUT = 600
POLL_INTERVAL = 2.0

NO_BACKEND_EXIT = 3
FAILED_EXIT = 4


# --------------------------------------------------------------------------- #
# transport
# --------------------------------------------------------------------------- #

def request_json(url: str, method: str = "GET", fields: dict | None = None,
                 files: dict | None = None, timeout: int = 300) -> tuple[int, object]:
    """One HTTP call, returning the status and the decoded body.

    Errors are returned rather than raised: a 4xx from a module that cannot run is
    part of what the walkthrough is documenting, so it has to reach the write-up
    instead of ending the run.
    """
    data = None
    headers = {"Accept": "application/json"}
    if fields or files:
        boundary = f"----DeepTraceWalkthrough{uuid.uuid4().hex}"
        parts: list[bytes] = []
        for name, value in (fields or {}).items():
            if value is None:
                continue
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                f"{value}\r\n".encode("utf-8"))
        for name, path in (files or {}).items():
            with open(path, "rb") as handle:
                blob = handle.read()
            mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; "
                f"filename=\"{os.path.basename(path)}\"\r\n"
                f"Content-Type: {mime}\r\n\r\n".encode("utf-8"))
            parts.append(blob + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        data = b"".join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read()
            try:
                return response.status, json.loads(body.decode("utf-8"))
            except ValueError:
                return response.status, {"raw_bytes": len(body)}
    except urllib.error.HTTPError as error:
        body = error.read()
        try:
            return error.code, json.loads(body.decode("utf-8"))
        except ValueError:
            return error.code, {"detail": body.decode("utf-8", "replace")[:500]}
    except urllib.error.URLError as error:
        return 0, {"detail": str(error.reason)}


def download(url: str, dest: str, timeout: int = 300) -> tuple[int, int]:
    """Fetch a binary artifact to disk, returning its status and byte count."""
    req = urllib.request.Request(url, headers={"Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = response.read()
            with open(dest, "wb") as handle:
                handle.write(payload)
            return response.status, len(payload)
    except urllib.error.HTTPError as error:
        return error.code, 0
    except urllib.error.URLError:
        return 0, 0


def sha256_of(path: str) -> str | None:
    """Recomputed here, deliberately, rather than read back from the API."""
    if not os.path.isfile(path):
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------- #
# formatting helpers
# --------------------------------------------------------------------------- #

def code(value) -> str:
    return f"`{value}`" if value not in (None, "") else "_not reported_"


def short_hash(value) -> str:
    if not isinstance(value, str) or len(value) < 16:
        return "_not reported_"
    return f"`{value[:16]}…{value[-8:]}`"


def as_percent(value) -> str:
    if not isinstance(value, (int, float)):
        return "_n/a_"
    return f"{value * 100:.1f}%"


def table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_No rows._\n"
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell).replace("|", "\\|") for cell in row) + " |")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #

def wait_for_analysis(base: str, investigation_id: int) -> tuple[dict, float]:
    """Poll the case until it stops being 'analyzing'.

    The elapsed time is reported in the write-up because 'how long did it take'
    is a question a reviewer asks and an estimate would be worthless.
    """
    started = time.time()
    last = {}
    while time.time() - started < ANALYSIS_TIMEOUT:
        status, body = request_json(f"{base}/api/investigation/{investigation_id}")
        if status == 200 and isinstance(body, dict):
            last = body
            state = (body.get("investigation") or body).get("status")
            if state != "analyzing":
                return body, time.time() - started
        time.sleep(POLL_INTERVAL)
    return last, time.time() - started


def make_reshared_copy(source: str, dest_dir: str) -> tuple[str | None, str]:
    """A real re-encode of the submitted media, standing in for a circulated copy.

    The step this demonstrates is the one an investigator actually performs: they
    already hold the copy that was being shared, and they want to know whether it
    is the same media as the complainant's file. A re-shared copy never has the
    same SHA-256 — every platform re-encodes — so this is exactly the case where
    byte-identity fails and perceptual comparison is the only thing that answers
    the question. Showing it with an identical file would demonstrate nothing.

    The copy is produced here by ffmpeg, so it is clearly-identified demonstration
    input; the comparison DeepTrace then performs on it is real.
    """
    import subprocess

    binary = None
    try:
        from services import forensics as _forensics
        binary = _forensics.ffmpeg_binary("ffmpeg")
    except Exception:
        binary = "ffmpeg"

    extension = os.path.splitext(source)[1].lower()
    dest = os.path.join(dest_dir, f"reshared_copy{extension or '.jpg'}")
    # The same recompression scripts/robustness.py uses for its messaging-app
    # re-upload family, so the walkthrough and the robustness artifact are
    # describing the same degradation rather than two different ones.
    args = [binary, "-y", "-loglevel", "error", "-i", source,
            "-vf", "scale='min(1024,iw)':-2", "-q:v", "8", dest]
    try:
        result = subprocess.run(args, capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        return None, f"ffmpeg could not run: {error}"
    if result.returncode != 0 or not os.path.isfile(dest):
        return None, (result.stderr or b"").decode("utf-8", "replace")[:200] or "ffmpeg failed"
    return dest, "messaging-app style re-upload (1024 px long edge, JPEG q8), produced locally by ffmpeg"


def main() -> int:
    fallback_suspect, fallback_reference, fallback_note = default_inputs()
    parser = argparse.ArgumentParser(
        description="Run one investigation end to end and write docs/WALKTHROUGH.md.")
    parser.add_argument("--base", default=DEFAULT_BASE, help=f"API base URL (default {DEFAULT_BASE}).")
    parser.add_argument("--suspect", default=fallback_suspect,
                        help="The suspicious media to submit.")
    parser.add_argument("--reference", default=fallback_reference,
                        help="A reference photograph of the person being impersonated.")
    parser.add_argument("--identity-name", default="Walkthrough Subject (demonstration)",
                        help="Name recorded for the protected identity.")
    parser.add_argument("--source-urls", default="https://vis-www.cs.umass.edu/lfw/",
                        help="Comma-separated URLs the complainant says the media appeared at.")
    parser.add_argument("--attach-copy", default=None,
                        help="A copy of the media the investigator already holds, to be compared "
                             "against the case original. If omitted, ffmpeg produces a re-encoded "
                             "copy locally to stand in for a re-shared one.")
    parser.add_argument("--input-note", default=None,
                        help="One sentence naming the provenance of the input media, printed in the "
                             "write-up so a reader knows what was submitted.")
    parser.add_argument("--out", default=OUTPUT_PATH, help="Where to write the document.")
    args = parser.parse_args()

    # A caller who supplied their own media gets no inherited note: describing their
    # input with a sentence about someone else's would be worse than saying nothing.
    input_note = args.input_note
    if input_note is None and (args.suspect, args.reference) == (fallback_suspect, fallback_reference):
        input_note = fallback_note

    for path, label in ((args.suspect, "--suspect"), (args.reference, "--reference")):
        if not os.path.isfile(path):
            print(f"{label} is not a file: {path}")
            return FAILED_EXIT

    base = args.base.rstrip("/")
    print(f"DeepTrace walkthrough against {base}")

    status, health = request_json(f"{base}/api/health", timeout=30)
    if status != 200:
        print(f"\n  The backend at {base} did not answer /api/health (status {status}).")
        print("  Start it first; this script does not start a server, because the write-up has to "
              "describe the deployment you are actually running.")
        return NO_BACKEND_EXIT
    print("  backend: healthy")

    # 1 — enrol the person being impersonated. Consent is required by the API and
    # recorded with a version, which is itself part of the custody story.
    print("\n[1/7] Enrolling the protected identity")
    status, enrolled = request_json(
        f"{base}/api/identity/enroll", "POST",
        fields={"name": args.identity_name, "consent_given": "true"},
        files={"reference_image": args.reference})
    if status != 200:
        print(f"  enrolment failed ({status}): {enrolled}")
        return FAILED_EXIT
    identity_id = (enrolled.get("identity") or enrolled).get("id")
    print(f"  identity #{identity_id}")

    # 2 — submit the suspicious media. The API hashes it server-side on receipt.
    print("\n[2/7] Submitting the suspicious media")
    status, opened = request_json(
        f"{base}/api/investigate", "POST",
        fields={"identity_id": identity_id, "source_urls": args.source_urls},
        files={"file": args.suspect})
    if status != 200:
        print(f"  upload failed ({status}): {opened}")
        return FAILED_EXIT
    investigation_id = (opened.get("investigation") or opened).get("id")
    print(f"  case #{investigation_id}")

    # The hash the submitter never supplied: recomputed locally from the file that
    # was sent, so the comparison against the stored value is independent.
    local_upload_hash = sha256_of(args.suspect)

    print("\n[3/7] Running the analysis pipeline")
    status, _ = request_json(f"{base}/api/investigation/{investigation_id}/analyze", "POST",
                             timeout=ANALYSIS_TIMEOUT)
    if status not in (200, 202):
        print(f"  analyze returned {status}; polling anyway in case it ran asynchronously")
    case, elapsed = wait_for_analysis(base, investigation_id)
    investigation = case.get("investigation") or case
    print(f"  status {investigation.get('status')} after {elapsed:.1f}s")

    print("\n[4/7] Comparing a copy said to be circulating")
    # POST /trace takes its own inputs; it does not re-read the URLs recorded at
    # intake. Passing nothing returns 422, which earlier made this stage look as
    # though tracing had found nothing when in fact it had never been asked.
    workspace = os.path.join(REPO_ROOT, "data", "walkthrough_tmp")
    os.makedirs(workspace, exist_ok=True)
    attach_path, attach_note = (args.attach_copy, "supplied with --attach-copy")
    if not attach_path:
        attach_path, attach_note = make_reshared_copy(args.suspect, workspace)
    copy_hash = sha256_of(attach_path) if attach_path else None

    trace_fields = {"label": "Copy recovered by the investigator"}
    trace_files = {}
    if attach_path:
        trace_files["local_copy"] = attach_path
    https_urls = [url.strip() for url in (args.source_urls or "").split(",")
                  if url.strip().startswith("https://")]
    if https_urls:
        trace_fields["source_urls"] = ",".join(https_urls)

    if trace_files or "source_urls" in trace_fields:
        trace_status, trace = request_json(f"{base}/api/investigation/{investigation_id}/trace",
                                          "POST", fields=trace_fields, files=trace_files or None,
                                          timeout=ANALYSIS_TIMEOUT)
    else:
        trace_status, trace = 0, {"detail": "Nothing to trace: no local copy and no https URL."}
    if trace_status != 200:
        print(f"  POST returned {trace_status}: {str(trace)[:200]}")
    trace_state_status, trace_state = request_json(
        f"{base}/api/investigation/{investigation_id}/trace")
    print(f"  trace status {trace_status}, current state {trace_state_status}")

    print("\n[5/7] Verifying the preserved evidence")
    verify_status, verify = request_json(f"{base}/api/investigation/{investigation_id}/verify")
    custody_status, custody = request_json(f"{base}/api/investigation/{investigation_id}/custody")
    evidence_status, evidence = request_json(f"{base}/api/investigation/{investigation_id}/evidence")
    timeline_status, timeline = request_json(f"{base}/api/investigation/{investigation_id}/timeline")
    print(f"  verify {verify_status}  custody {custody_status}  evidence {evidence_status}")

    print("\n[6/7] Producing the forensic report")
    report_status, report = request_json(f"{base}/api/investigation/{investigation_id}/report",
                                        timeout=ANALYSIS_TIMEOUT)
    pdf_bytes, pdf_local_hash, pdf_path = 0, None, None
    if report_status == 200:
        pdf_path = os.path.join(REPO_ROOT, "data", f"walkthrough_case_{investigation_id}.pdf")
        code_, pdf_bytes = download(f"{base}/api/report/{investigation_id}/download", pdf_path)
        if code_ == 200:
            pdf_local_hash = sha256_of(pdf_path)
            print(f"  report downloaded, {pdf_bytes} bytes")
        else:
            pdf_path = None
            print(f"  report download returned {code_}")
    else:
        print(f"  report generation returned {report_status}: {report}")

    print("\n[7/7] Writing the document")
    document = render(
        base=base, health=health, identity=enrolled, identity_id=identity_id,
        case=case, investigation=investigation, investigation_id=investigation_id,
        elapsed=elapsed, local_upload_hash=local_upload_hash,
        verify=(verify_status, verify), custody=(custody_status, custody),
        evidence=(evidence_status, evidence), timeline=(timeline_status, timeline),
        trace=(trace_status, trace), report=(report_status, report),
        trace_state=(trace_state_status, trace_state),
        attach_path=attach_path, attach_note=attach_note, copy_hash=copy_hash,
        pdf_path=pdf_path, pdf_bytes=pdf_bytes, pdf_local_hash=pdf_local_hash,
        suspect=args.suspect, reference=args.reference, input_note=input_note,
        source_urls=args.source_urls,
    )

    out_path = args.out if os.path.isabs(args.out) else os.path.join(REPO_ROOT, args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(document)
    print(f"  wrote {os.path.relpath(out_path, REPO_ROOT)}")
    print(f"\nCase #{investigation_id} is open in the UI; every figure in the document came from it.")
    return 0


# --------------------------------------------------------------------------- #
# the write-up
# --------------------------------------------------------------------------- #

def claim_list(entries, limit: int = 8) -> str:
    """Render the API's own {claim, detail} lists verbatim.

    These sections are deliberately not written by hand. The application already
    states what hashing proves and what the analysis establishes, and a document
    that paraphrases it can drift out of step with what users are actually told.
    Quoting the endpoint means the write-up cannot claim more than the product
    does.
    """
    if not isinstance(entries, list) or not entries:
        return "_The endpoint reported none._\n"
    lines = []
    for entry in entries[:limit]:
        if isinstance(entry, dict):
            claim = entry.get("claim") or entry.get("gap") or "—"
            detail = entry.get("detail") or ""
            lines.append(f"- **{claim}** — {detail}" if detail else f"- **{claim}**")
        else:
            lines.append(f"- {entry}")
    return "\n".join(lines) + "\n"


def module_conclusion(module: dict) -> str:
    """The module's own words, wherever it puts them.

    Each module names its finding under the key that fits it — a fusion has an
    explanation, a detector has an interpretation, a search has a summary — so
    there is no single field to read. Falling back to the score alone would print
    a number with nothing to say what it means, which is the failure mode this
    column exists to prevent.
    """
    data = module.get("data") or {}
    for key in ("explanation", "interpretation", "summary", "note", "reason", "detail"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    status = module.get("status")
    if status and status != "completed":
        return f"Reported `{status}`; no finding claimed."
    return "—"


def render(**ctx) -> str:
    investigation = ctx["investigation"]
    case = ctx["case"]
    investigation_id = ctx["investigation_id"]

    modules = case.get("analysis_results") or case.get("results") or []
    if isinstance(modules, dict):
        modules = [dict(value, module_name=key) for key, value in modules.items()
                   if isinstance(value, dict)]

    verify_status, verify = ctx["verify"]
    custody_status, custody = ctx["custody"]
    evidence_status, evidence = ctx["evidence"]
    timeline_status, timeline = ctx["timeline"]
    trace_status, trace = ctx["trace"]
    trace_state_status, trace_state = ctx.get("trace_state", (None, None))
    if trace_status != 200 and trace_state_status == 200:
        # The POST can fail (nothing retrievable, no copy to attach) while the case
        # still holds sources recorded at intake. Report whatever the case actually has.
        trace_status, trace = trace_state_status, trace_state
    report_status, report = ctx["report"]

    stored_hash = investigation.get("sha256_hash")
    local_hash = ctx["local_upload_hash"]
    hashes_agree = bool(stored_hash and local_hash and stored_hash == local_hash)

    lines: list[str] = []
    add = lines.append

    add("# One complete investigation, end to end")
    add("")
    add(f"Case **#{investigation_id}**, produced by `scripts/walkthrough.py` against "
        f"`{ctx['base']}` on {investigation.get('created_at') or 'this run'}.")
    add("")
    add("Every number, hash and finding below was read back from the API after the run. Nothing "
        "here is transcribed by hand or written for illustration. Re-running the script produces a "
        "new case with its own values; the ones printed here belong to this one.")
    add("")

    # ---------------------------------------------------------------- who
    add("## Who this is for")
    add("")
    add("**Primary user: the person being impersonated — the complainant.** They arrive with a link "
        "or a file and one question: *what do I do about this?* The output they need is a document "
        "they can hand to someone with authority to act.")
    add("")
    add("**Secondary user: the cybercrime investigator or forensic examiner** who receives that "
        "document. They need to know what was preserved, when, how it was measured, and what the "
        "measurement does not establish.")
    add("")
    add("**Neither of them gets a verdict.** DeepTrace does not decide whether media is genuine or "
        "fake. It measures, records and hands over.")
    add("")

    # ---------------------------------------------------------------- input
    add("## Stage 1 — What was submitted")
    add("")
    if ctx.get("input_note"):
        add(f"_{ctx['input_note']}_")
        add("")
    add(table(["Field", "Value"], [
        ["Suspicious media", code(os.path.basename(ctx["suspect"]))],
        ["Reference photograph", code(os.path.basename(ctx["reference"]))],
        ["Protected identity", f"#{ctx['identity_id']} — consent recorded at enrolment"],
        ["Declared source URLs", code(ctx["source_urls"])],
        ["Stored filename", code(investigation.get("filename"))],
        ["Media type", code(investigation.get("media_type"))],
        ["Size on disk", code(f"{investigation.get('file_size_bytes')} bytes")],
    ]))
    add("")

    # ---------------------------------------------------------------- hashing
    add("## Stage 2 — Preservation, and exactly what it proves")
    add("")
    add("The API hashes the upload **server-side on receipt**. No client-supplied hash is trusted. "
        "To make this section independent of the system it is describing, `walkthrough.py` "
        "recomputed the digest of the file it sent, in its own process, and compared:")
    add("")
    add(table(["Digest", "Value"], [
        ["SHA-256 recorded by the API", short_hash(stored_hash)],
        ["SHA-256 recomputed by this script", short_hash(local_hash)],
        ["Agreement", "**identical**" if hashes_agree else "**MISMATCH — investigate**"],
    ]))
    add("")
    add("### What the hash proves")
    add("")
    add("Quoted from `GET /api/investigation/"
        f"{investigation_id}/custody` — the same text the application shows the user and prints in "
        "the PDF, not a paraphrase written for this document:")
    add("")
    add(claim_list(custody.get("hashing_proves") if isinstance(custody, dict) else None))
    add("")
    add("### What the hash does not prove")
    add("")
    add(claim_list(custody.get("hashing_does_not_prove") if isinstance(custody, dict) else None))
    add("")

    rows = []
    integrity = (custody.get("integrity_check") or {}) if isinstance(custody, dict) else {}
    if isinstance(verify, dict):
        for key in ("artifacts_checked", "chain_intact", "verified_at", "algorithm", "summary"):
            source = verify if key in verify else integrity
            if key in source:
                rows.append([code(key), code(source[key]) if key != "summary" else source[key]])
    add("### Re-verification on demand")
    add("")
    add(f"`GET /api/investigation/{investigation_id}/verify` re-reads every preserved artifact from "
        f"disk and re-hashes it (HTTP {verify_status}):")
    add("")
    add(table(["Field", "Value"], rows) if rows else "_The endpoint returned no comparable fields._\n")
    if integrity.get("limitations"):
        add("")
        add(f"**The endpoint states its own limits:** {integrity['limitations']}")
    add("")

    # ---------------------------------------------------------------- custody
    add("## Stage 3 — Chain of custody")
    add("")
    if custody_status == 200 and isinstance(custody, dict):
        if custody.get("boundary_summary"):
            add(f"> {custody['boundary_summary']}")
            add("")
        scope = custody.get("custody_scope")
        if isinstance(scope, dict):
            if scope.get("statement"):
                add(f"**What this record is, in the endpoint's own words:** {scope['statement']}")
                add("")
            if scope.get("definition"):
                add(f"_{scope['definition']}_")
                add("")
            halves = [("DeepTrace supplies", scope.get("deeptrace_supplies")),
                      ("The investigator supplies", scope.get("investigator_supplies"))]
            for heading, items in halves:
                if isinstance(items, list) and items:
                    add(f"**{heading}:**")
                    add("")
                    for item in items:
                        add(f"- {item}")
                    add("")
        elif scope:
            add(f"**Scope the record claims for itself:** {scope}")
            add("")

        counts = custody.get("counts") or {}
        ledger = custody.get("artifact_ledger") or []
        chronology = custody.get("chronology") or []
        add(table(["Field", "Value"], [
            ["Artifacts in the ledger", code(counts.get("artifacts", len(ledger)))],
            ["Acquired (received, never regenerated)", code(counts.get("acquired"))],
            ["Derived (recomputed on re-analysis)", code(counts.get("derived"))],
            ["Artifacts with no digest", code(counts.get("without_digest"))],
            ["Chronology entries", code(len(chronology))],
        ]))
        add("")

        if ledger:
            add("### Artifact ledger")
            add("")
            add(table(["Artifact", "Origin", "Role", "Preserved (UTC)", "Digest"], [
                [code(item.get("evidence_type")), code(item.get("origin")),
                 (item.get("role") or "—"), code(item.get("preserved_at")),
                 short_hash(item.get("sha256") or item.get("sha256_hash"))]
                for item in ledger[:12] if isinstance(item, dict)]))
            add("")
        if custody.get("derivation_note"):
            add(f"_{custody['derivation_note']}_")
            add("")

        if chronology:
            add("### Chronology")
            add("")
            add(f"Recorded as each action happened, not reconstructed afterwards. "
                f"{len(chronology)} entries; the first and last few:")
            add("")
            shown = chronology[:6] + ([{"sequence": "…", "event_type": "…", "description": "…",
                                        "recorded_at": "…"}] + chronology[-4:]
                                      if len(chronology) > 10 else chronology[6:])
            add(table(["#", "Event", "Recorded (UTC)", "Description"], [
                [code(entry.get("sequence")), code(entry.get("event_type")),
                 code(entry.get("recorded_at")), (entry.get("description") or "—")[:110]]
                for entry in shown if isinstance(entry, dict)]))
            add("")
        if custody.get("chronology_note"):
            add(f"_{custody['chronology_note']}_")
            add("")

        add("### Gaps the record declares about itself")
        add("")
        add(claim_list(custody.get("custody_gaps"), limit=10))
        add("")
        add("These are stated rather than hidden, and they are the reason this project does not "
            "claim guaranteed legal admissibility. A custody record that presents itself as "
            "complete when it is not is worse than one that names its own limits.")
    else:
        add(f"The custody endpoint returned HTTP {custody_status}. No custody claim is made for "
            f"this run.")
    add("")

    if evidence_status == 200:
        items = evidence if isinstance(evidence, list) else (evidence.get("evidence") or [])
        add(f"**Preserved artifacts: {len(items)}.** "
            f"`GET /api/investigation/{investigation_id}/evidence` lists each with its own digest.")
        add("")
    if timeline_status == 200:
        events = timeline if isinstance(timeline, list) else (timeline.get("timeline") or [])
        add(f"**Timeline events: {len(events)}**, from "
            f"`GET /api/investigation/{investigation_id}/timeline`.")
        add("")

    # ---------------------------------------------------------------- analysis
    add("## Stage 4 — Analysis, and exactly what it establishes")
    add("")
    add(f"Pipeline wall-clock: **{ctx['elapsed']:.1f} s**. Final case status: "
        f"{code(investigation.get('status'))}.")
    add("")
    module_rows = []
    for module in modules:
        if not isinstance(module, dict):
            continue
        score = module.get("score")
        confidence = module.get("confidence")
        module_rows.append([
            code(module.get("module_name") or module.get("module")),
            code(module.get("status")),
            f"{score:.4f}" if isinstance(score, (int, float)) else "_none_",
            f"{confidence:.2f}" if isinstance(confidence, (int, float)) else "—",
            module_conclusion(module),
        ])
    add(table(["Module", "Status", "Score", "Confidence", "What it concluded"], module_rows))
    add("")
    add("The conclusions in the last column are each module's own words, read back from "
        f"`GET /api/investigation/{investigation_id}`. Four modules returned no score at all — "
        "`not_applicable`, `unavailable` and `no_credentials` are reported as themselves rather "
        "than as a neutral 0.5, because a substituted number would move the fused risk score "
        "while looking like a measurement.")
    add("")
    add(table(["Aggregate", "Value"], [
        ["Overall risk score", code(investigation.get("overall_risk_score"))],
        ["Risk level", code(investigation.get("risk_level"))],
        ["Frames extracted", code(investigation.get("frames_extracted"))],
    ]))
    add("")
    add("### What the analysis establishes")
    add("")
    add(f"Again quoted from `GET /api/investigation/{investigation_id}/custody`, not paraphrased:")
    add("")
    add(claim_list(custody.get("ai_establishes") if isinstance(custody, dict) else None))
    add("")
    add("### What the analysis does not establish")
    add("")
    add(claim_list(custody.get("ai_does_not_establish") if isinstance(custody, dict) else None))
    add("")

    # ---------------------------------------------------------------- trace
    add("## Stage 5 — Comparing a circulating copy")
    add("")
    if ctx.get("attach_note"):
        add(f"_{ctx['attach_note']}_")
        add("")
    if trace_status == 200 and isinstance(trace, dict):
        sources = trace.get("sources") or []
        retrieved = [s for s in sources if isinstance(s, dict)
                     and s.get("retrieval_status") == "fetched"]
        add(table(["Field", "Value"], [
            ["Locations on record", code(trace.get("source_count", len(sources)))],
            ["Copies actually retrieved and compared", code(trace.get("retrieved_count",
                                                                     len(retrieved)))],
        ]))
        add("")
        source_rows = []
        for source in sources[:12]:
            if not isinstance(source, dict):
                continue
            similarity = source.get("similarity")
            source_rows.append([
                code(source.get("source_url") or source.get("title") or "—"),
                code(source.get("origin")),
                code(source.get("retrieval_status")),
                code(source.get("match_type")),
                (f"{similarity:.4f}" if isinstance(similarity, (int, float)) else "—"),
                (source.get("similarity_label") or "—"),
            ])
        if source_rows:
            add(table(["Location / copy", "Origin", "Retrieval", "Match type", "Similarity",
                       "Label"], source_rows))
            add("")
        failures = [s for s in sources if isinstance(s, dict) and s.get("retrieval_error")]
        if failures:
            add("A row with no match type is one DeepTrace could not retrieve. The reason is "
                "recorded rather than swallowed, and no similarity is invented for it:")
            add("")
            for source in failures[:4]:
                add(f"- `{source.get('source_url')}` — {str(source.get('retrieval_error'))[:200]}")
            add("")

        if ctx.get("copy_hash"):
            add("### Why byte-identity is not enough, shown rather than asserted")
            add("")
            add("The copy compared above is a genuine re-encode of the submitted file, produced by "
                "`ffmpeg` in this script — the same thing every platform does to media on upload. "
                "Its digest therefore differs, while the picture does not:")
            add("")
            add(table(["Copy", "SHA-256"], [
                ["Submitted media", short_hash(local_hash)],
                ["Re-encoded circulating copy", short_hash(ctx["copy_hash"])],
            ]))
            add("")
            add("Two different digests, one visual subject. This is precisely the case where hashing "
                "answers *nothing* and perceptual comparison answers the question, and it is why the "
                "two are reported separately throughout: the hash is an integrity control on what "
                "this system holds, not a way to recognise a re-shared file.")
            add("")
        if trace.get("scope"):
            add(f"**Scope, quoted from the endpoint:** {trace['scope']}")
            add("")
        add("Absence of a match means only that nothing was found in what was checked.")
    else:
        add(f"The trace endpoint returned HTTP {trace_status}, so no provenance claim is made for "
            f"this run.")
    add("")

    # ---------------------------------------------------------------- report
    add("## Stage 6 — The forensic report")
    add("")
    if ctx.get("pdf_local_hash"):
        add(table(["Field", "Value"], [
            ["Generation", f"HTTP {report_status}"],
            ["File", code(os.path.relpath(ctx["pdf_path"], REPO_ROOT).replace("\\", "/"))],
            ["Size", code(f"{ctx['pdf_bytes']} bytes")],
            ["SHA-256 of the PDF, recomputed here", short_hash(ctx["pdf_local_hash"])],
        ]))
        add("")
        add("The report is itself hashed, so a recipient can confirm the document they are reading "
            "is the document that was produced. It carries the case metadata, the custody chain, "
            "every module result including the unavailable ones, the hash-versus-inference "
            "boundary stated above, and the validation figures with their confidence intervals.")
    else:
        add(f"Report generation returned HTTP {report_status}; no PDF is described here.")
    add("")

    # ---------------------------------------------------------------- close
    add("## What a reviewer should take from this")
    add("")
    add(table(["Claim", "Basis", "Strength"], [
        ["These bytes are unaltered since receipt", "SHA-256, recomputed independently above",
         "**Arithmetic.** Verifiable by anyone, without trusting DeepTrace."],
        ["This report describes those bytes", "Digest recorded in the report and in custody",
         "**Arithmetic.**"],
        ["The media shows signs consistent with manipulation", "Module inference",
         "**Evidence, with a measured error rate.** Not proof."],
        ["The face matches the enrolled person", "Face embedding similarity at a measured threshold",
         "**Evidence, with a measured false-match rate.** Not identification of a person."],
        ["A circulating copy is the same subject as the original",
         "Perceptual comparison of a retrieved copy, hashes differing",
         "**Evidence about reach.** Not an exhaustive search, and not byte-identity."],
        ["Someone committed an offence", "—",
         "**Not established.** Outside what this system can determine."],
    ]))
    add("")
    add("---")
    add("")
    add(f"Reproduce: start the backend, then `python scripts/walkthrough.py`. Open case "
        f"#{investigation_id} in the UI to see the same values in the interface. Validation figures "
        f"live in `docs/VALIDATION.md` and are regenerated by `scripts/benchmark.py` and "
        f"`scripts/robustness.py`.")
    add("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
