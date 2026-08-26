"""Forensic incident report generation.

Twenty-three sections, every value read from what the pipeline actually recorded. A
module that did not run is printed as not-run, with the reason it gave — no
section is filled with a plausible-looking placeholder, and the limitations
section is assembled from the observed module statuses rather than a fixed list.

Section 22 is the one exception to "everything here describes this case": it
reports how the system itself scored on DeepTrace's own validation harnesses, and
is labelled as such, because a case score means little to a reviewer who has no
measurement of the detector producing it.
"""

import os
from html import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from paths import PROJECT_ROOT, report_path, to_public_path
from services.validation import (
    BOUNDARY as VALIDATION_BOUNDARY,
    METRICS_COMMAND,
    ROBUSTNESS_COMMAND,
    load_metrics,
    load_robustness,
)

NAVY = colors.HexColor("#0b3954")
SAFFRON = colors.HexColor("#b45309")
GREY = colors.HexColor("#9aaab5")
LIGHT = colors.HexColor("#e8eef2")

CONTENT_WIDTH = 180 * mm

STATUS_LABELS = {
    "completed": "Completed",
    "unavailable": "Unavailable",
    "not_applicable": "Not applicable",
    "no_credentials": "No credentials present",
    "not_run": "Not run",
}


def _text(value) -> str:
    if value is None or value == "":
        return "Not recorded"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def _score(value, digits: int = 3) -> str:
    if value is None:
        return "Not produced"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _seconds(value) -> str:
    if value is None:
        return "—"
    try:
        total = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{int(total // 60):02d}:{total % 60:05.2f}"


def _ratio(value) -> str:
    """Format a validation ratio.

    Distinct from ``_score`` in the one way that matters: a missing validation
    metric is *undefined* (a class was absent, so the ratio has no denominator),
    not merely unproduced, and it must never render as 0.000.
    """
    if value is None:
        return "Not defined"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)


def _interval(value) -> str:
    """Render a 95% confidence interval, or say plainly that there is none."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return "—"
    try:
        return f"{float(value[0]):.3f} – {float(value[1]):.3f}"
    except (TypeError, ValueError):
        return "—"


def _status_label(payload: dict | None) -> str:
    if not payload:
        return "Not run"
    return STATUS_LABELS.get(payload.get("status"), _text(payload.get("status")))


def _archive_stamp(value) -> str:
    """Wayback CDX timestamps are YYYYMMDDhhmmss, which reads as a number.

    Rendered as a date so a reader does not mistake a capture time for an ID —
    and left verbatim if it is not that shape, rather than silently reformatted.
    """
    text = _text(value)
    if len(text) >= 8 and text[:8].isdigit():
        stamp = f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
        return f"{stamp} {text[8:10]}:{text[10:12]} UTC" if len(text) >= 12 else stamp
    return text or "—"


def on_disk(path: str | None) -> str | None:
    """Resolve a stored artifact path to a readable file, or None.

    Module payloads store repository-relative paths so the API never leaks the
    operator's directory layout. Resolving them against ``PROJECT_ROOT`` rather
    than the working directory keeps report generation correct no matter where
    the backend was launched from. Absolute paths (legacy rows) still work.
    """
    if not path:
        return None
    candidate = path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path.replace("/", os.sep))
    return candidate if os.path.isfile(candidate) else None


def generate_report(investigation_id: int, db_session) -> str | None:
    from models.schema import Identity, Investigation
    from services.custody import build_custody_record
    from services.integrity import verify_investigation
    from services.response import build_guidance

    inv = (db_session.query(Investigation)
           .filter(Investigation.id == investigation_id)
           .first())
    if not inv:
        return None

    identity = (db_session.query(Identity).filter(Identity.id == inv.identity_id).first()
                if inv.identity_id else None)

    latest: dict[str, object] = {}
    for row in sorted(inv.analysis_results, key=lambda r: (str(r.created_at or ""), r.id)):
        latest[row.module_name] = row

    def data_for(module: str) -> dict | None:
        row = latest.get(module)
        return (getattr(row, "result_data", None) or None) if row else None

    metadata = data_for("metadata")
    deepfake = data_for("deepfake")
    localization = data_for("localization")
    identity_result = data_for("identity")
    voice = data_for("voice")
    audio = data_for("audio")
    consistency = data_for("consistency")
    provenance = data_for("provenance")
    propagation = data_for("similarity")
    risk = data_for("risk_fusion")

    evidence_items = sorted(inv.evidence_items, key=lambda e: (e.evidence_type or "", e.id))
    integrity = verify_investigation([
        {
            "id": item.id,
            "evidence_type": item.evidence_type,
            "file_path": item.file_path,
            "sha256_hash": item.sha256_hash,
            "public_path": to_public_path(item.file_path),
            "timestamp_offset": item.timestamp_offset,
            "created_at": str(item.created_at) if item.created_at else None,
        }
        for item in evidence_items
    ])
    custody = build_custody_record(inv, integrity, identity)
    trace_sources = [
        {
            "source_url": source.source_url,
            "title": source.title,
            "origin": source.origin,
            "retrieval_status": source.retrieval_status,
            "retrieval_error": source.retrieval_error,
            "sha256": source.sha256_hash,
            "similarity": source.similarity,
            "match_type": source.match_type,
            "similarity_label": source.similarity_label,
            "bytes_downloaded": source.bytes_downloaded,
        }
        for source in inv.trace_sources
    ]
    guidance = build_guidance(
        investigation={
            "id": inv.id, "filename": inv.filename, "media_type": inv.media_type,
            "risk_level": inv.risk_level, "frames_extracted": inv.frames_extracted,
        },
        risk=risk, deepfake=deepfake, identity=identity_result, voice=voice,
        localization=localization, propagation=propagation, provenance=provenance,
        trace_sources=trace_sources, integrity=integrity,
    )

    # ── Styles ───────────────────────────────────────────────────────────────
    styles = getSampleStyleSheet()
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=8.6, leading=11.4,
                          spaceAfter=4)
    small = ParagraphStyle("Small", parent=body, fontSize=7.6, leading=9.6, spaceAfter=2)
    mono = ParagraphStyle("Mono", parent=small, fontName="Courier", fontSize=6.8, leading=8.4)
    caption = ParagraphStyle("Caption", parent=small, fontSize=6.6, leading=8,
                             alignment=TA_CENTER, textColor=colors.HexColor("#44586b"))
    heading = ParagraphStyle("Heading", parent=styles["Heading2"], fontSize=11, leading=14,
                             textColor=NAVY, spaceBefore=13, spaceAfter=5)
    subheading = ParagraphStyle("Subheading", parent=styles["Heading4"], fontSize=8.8,
                                leading=11, textColor=SAFFRON, spaceBefore=7, spaceAfter=3)
    title_style = ParagraphStyle("DocTitle", parent=styles["Title"], fontSize=19, leading=23,
                                 textColor=NAVY, spaceAfter=2)
    subtitle = ParagraphStyle("Subtitle", parent=body, fontSize=9.4, leading=12,
                              alignment=TA_CENTER, textColor=colors.HexColor("#44586b"))

    story: list = []
    counter = {"n": 0}

    def section(name: str) -> None:
        counter["n"] += 1
        story.append(Paragraph(f"{counter['n']}. {escape(name)}", heading))

    def para(value, style=body) -> None:
        story.append(Paragraph(escape(_text(value)), style))

    def keyvalues(rows: list[tuple[str, object]]) -> None:
        cells = [[Paragraph(escape(key), small), Paragraph(escape(_text(value)), small)]
                 for key, value in rows]
        table = Table(cells, colWidths=[45 * mm, CONTENT_WIDTH - 45 * mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), LIGHT),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.35, GREY),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(table)

    def grid(header: list[str], rows: list[list[object]], widths: list[float],
             styles_for_cells=None) -> None:
        cell_style = styles_for_cells or small
        table_data = [[Paragraph(f"<b>{escape(h)}</b>", small) for h in header]]
        for row in rows:
            table_data.append([
                cell if isinstance(cell, (Paragraph, Image))
                else Paragraph(escape(_text(cell)), cell_style)
                for cell in row
            ])
        table = Table(table_data, colWidths=widths, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.35, GREY),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(table)

    def claims_table(entries: list[dict], first_column: str) -> None:
        """Render one of the custody claim lists as a statement/basis table."""
        grid([first_column, "Basis for that statement"],
             [[Paragraph(f"<b>{escape(entry['claim'])}</b>", small), entry["detail"]]
              for entry in entries],
             [62 * mm, CONTENT_WIDTH - 62 * mm])

    def _located_sources(search: dict) -> None:
        """Where else this media was found, and how much of that was verified.

        Discovery and verification are printed as separate counts. A page returned
        by a reverse-image index is a lead; only a page whose served media matched
        this file on DeepTrace's own comparison is printed as a match. Merging the
        two numbers would let a third party's similarity guess read as a forensic
        finding in a document intended for an investigator.
        """
        story.append(Paragraph("Located sources (reverse-image search and local verification)",
                               subheading))
        status = search.get("status")
        if status != "completed":
            keyvalues([
                ("Status", _status_label(search) if search else "Did not run"),
                ("Reason", search.get("reason") or "No external source search was recorded."),
                ("Engine", search.get("engine") or "Not applicable"),
            ])
            para("No source list is reported. An unavailable or empty search is not evidence that "
                 "the media was never published elsewhere.", small)
            return

        keyvalues([
            ("Discovery engine", search.get("engine")),
            ("Query frames submitted", search.get("frames_searched")),
            ("Raw index matches", search.get("raw_match_count")),
            ("Unique candidate pages", search.get("unique_source_count")),
            ("Pages verified locally", search.get("sources_checked")),
            ("Pages whose media matched this file", search.get("sources_verified")),
            ("Pages that could not be retrieved", search.get("sources_unreachable")),
            ("Candidate video download", search.get("candidate_video_download")),
            ("Earliest archived capture among matches",
             f"{_archive_stamp(search.get('earliest_observed_at'))} — {search.get('earliest_observed_url')}"
             if search.get("earliest_observed_at") else "None recorded"),
        ])

        sources = [item for item in (search.get("sources") or []) if isinstance(item, dict)]
        if sources:
            grid(["#", "Source URL", "Result", "Media similarity", "Face", "First archived"],
                 [[
                     index,
                     Paragraph(escape(str(item.get("url") or "Not recorded")), mono),
                     (item.get("status") or "unknown").replace("_", " "),
                     _score(item.get("media_score")) if item.get("media_score") is not None else "—",
                     _score(item.get("face_similarity")) if item.get("face_similarity") is not None else "—",
                     _archive_stamp(item.get("first_observed")),
                 ] for index, item in enumerate(sources, 1)],
                 [8 * mm, CONTENT_WIDTH - 88 * mm, 26 * mm, 22 * mm, 14 * mm, 18 * mm])

            matched = [item for item in sources if item.get("media_verified")]
            if matched:
                story.append(Paragraph("Verified matches in detail", subheading))
                for item in matched:
                    keyvalues([
                        ("Source", item.get("url")),
                        ("Platform", item.get("platform")),
                        ("Matched on", item.get("verified_on")),
                        ("Relationship", (item.get("classification") or "").replace("_", " ").lower()),
                        ("Media similarity", _score(item.get("media_score"))),
                        ("Face similarity", _score(item.get("face_similarity"))
                                            if item.get("face_similarity") is not None
                                            else "No comparable face"),
                        ("Matching media SHA-256", item.get("media_sha256")),
                        ("Page reports publication", item.get("published_at") or "Not stated"),
                        ("Earliest archived capture", _archive_stamp(item.get("first_observed"))),
                        ("Retrieved at", item.get("checked_at")),
                    ])

        if search.get("interpretation"):
            para(search["interpretation"], small)
        if search.get("verification_method"):
            para(search["verification_method"], small)
        for text in (search.get("limitations") or []):
            para(f"• {text}", small)

    def not_run(payload: dict | None, module_label: str) -> bool:
        """Print an honest not-run block. Returns True when the section is closed."""
        if payload and payload.get("status") == "completed":
            return False
        reason = (payload or {}).get("reason") or (payload or {}).get("details")
        if not payload:
            reason = f"{module_label} did not run for this investigation."
        keyvalues([
            ("Status", _status_label(payload)),
            ("Reason", reason or "No reason was recorded."),
            ("Method", (payload or {}).get("method") or "Not applicable"),
        ])
        para("No score, finding or conclusion is reported for this module. An unavailable module "
             "is neither evidence of authenticity nor evidence of manipulation.", small)
        return True

    def thumbnails(entries: list[tuple[str, str]], per_row: int = 4) -> None:
        """Lay out available image files with captions. Missing files are skipped."""
        cells: list[list] = []
        width = (CONTENT_WIDTH - 6 * mm) / per_row
        row: list = []
        for path, label in entries:
            resolved = on_disk(path)
            if not resolved:
                continue
            try:
                image = Image(resolved, width=width - 3 * mm, height=(width - 3 * mm) * 0.62)
            except Exception:
                continue
            row.append([image, Paragraph(escape(label), caption)])
            if len(row) == per_row:
                cells.append(row)
                row = []
        if row:
            row.extend([""] * (per_row - len(row)))
            cells.append(row)
        if not cells:
            para("No preview image is available on disk for these frames.", small)
            return
        table = Table(cells, colWidths=[width] * per_row)
        table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(table)

    # ── Cover ────────────────────────────────────────────────────────────────
    story.append(Paragraph("DeepTrace Forensic Incident Report", title_style))
    story.append(Paragraph(
        "Intelligent Digital Impersonation Detection &amp; Forensic Evidence Preservation",
        subtitle))
    story.append(Spacer(1, 7 * mm))
    keyvalues([
        ("Case reference", f"DeepTrace INV-{inv.id:05d}"),
        ("Subject media", inv.filename),
        ("Assessed risk", f"{inv.risk_level or 'Not assessed'}"
                          f"{f' ({inv.overall_risk_score:.2f})' if inv.overall_risk_score is not None else ''}"),
        ("Protected identity", identity.name if identity else "None attached to this case"),
        ("Analysis completed", inv.analysis_completed_at or "Analysis has not completed"),
        ("Report generated", integrity["verified_at"]),
        ("Evidence integrity", integrity["summary"]),
    ])
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph(
        "<b>Scope of this document.</b> This report records what DeepTrace measured and preserved. "
        "The scores it contains are forensic indicators produced by research models, intended to "
        "direct expert review. They are not proof of manipulation, not proof of identity, not "
        "attribution of authorship, and not a determination of criminal conduct. DeepTrace does not "
        "claim perfect detection, does not monitor the internet, does not identify who created the "
        "media, and does not by itself establish legal admissibility.", body))

    # 1 ─────────────────────────────────────────────────────────────────────
    section("Case Summary")
    if risk:
        para(risk.get("explanation"))
        keyvalues([
            ("Overall risk", f"{risk.get('risk_level')} — {_score(risk.get('overall_risk_score'), 3)} "
                             f"on a 0–1 scale"),
            ("Signals contributing", f"{risk.get('signals_used')} available, "
                                     f"{risk.get('signals_excluded')} excluded as unavailable"),
            ("Dominant contributor", (risk.get("dominant_signal") or {}).get("label", "None")),
        ])
    else:
        para("Risk fusion has not run for this investigation, so no overall assessment is "
             "available. The sections below report each module's own status.")
    if guidance.get("case_findings"):
        story.append(Paragraph("Findings at a glance", subheading))
        for finding in guidance["case_findings"]:
            para(f"• {finding}", small)

    # 2 ─────────────────────────────────────────────────────────────────────
    section("Investigation Details")
    keyvalues([
        ("Investigation ID", inv.id),
        ("Original filename", inv.filename),
        ("Stored filename", os.path.basename(inv.file_path or "")),
        ("Media type", inv.media_type),
        ("File size", f"{inv.file_size_bytes:,} bytes" if inv.file_size_bytes else None),
        ("Case opened", inv.created_at),
        ("Analysis started", inv.analysis_started_at),
        ("Analysis completed", inv.analysis_completed_at),
        ("Case status", inv.status),
        ("Failure detail", inv.error_message or "None"),
    ])

    # 3 ─────────────────────────────────────────────────────────────────────
    section("Submitted Media")
    keyvalues([
        ("Duration", f"{inv.duration_seconds:.2f} seconds" if inv.duration_seconds else "Not applicable"),
        ("Resolution", inv.resolution),
        ("Frame rate", f"{inv.fps:.3f} fps" if inv.fps else None),
        ("Audio stream present", inv.has_audio_stream),
        ("Frames sampled for analysis", inv.frames_extracted or 0),
    ])
    if inv.media_type == "image" and on_disk(inv.file_path):
        story.append(Spacer(1, 2 * mm))
        thumbnails([(inv.file_path, "Submitted image")], per_row=2)

    # 4 ─────────────────────────────────────────────────────────────────────
    section("Protected Identity and Consent Record")
    if identity:
        keyvalues([
            ("Identity name", identity.name),
            ("Enrolled on", identity.created_at),
            ("Face template", f"{identity.face_model or 'Unknown model'}, "
                              f"{len(identity.face_embedding) if identity.face_embedding else 0} dimensions"),
            ("Voice template", identity.voice_model or "No voice reference enrolled"),
            ("Consent recorded", identity.consent_given),
            ("Consent text version", identity.consent_text_version),
            ("Consent timestamp", identity.consent_at),
        ])
        para("Biometric templates are numeric embeddings stored locally alongside the reference "
             "media supplied at enrollment. They were created under the recorded consent version.",
             small)
    else:
        para("No protected identity is attached to this case. DeepTrace therefore measured "
             "manipulation and preserved evidence, but made no determination about whom the media "
             "depicts. Impersonation assessment requires an enrolled, consented reference.")

    # 5 ─────────────────────────────────────────────────────────────────────
    section("Evidence Register and Hash Values")
    keyvalues([
        ("Original media SHA-256", inv.sha256_hash),
        ("Original media perceptual hash", inv.perceptual_hash or "Not applicable to this media type"),
        ("Hash provenance", "Computed server-side while the upload was written to disk. "
                            "Client-supplied hashes are never accepted."),
        ("Artifacts preserved", len(evidence_items)),
    ])
    story.append(Spacer(1, 2 * mm))
    rows = []
    for item in evidence_items:
        rows.append([
            item.id,
            (item.evidence_type or "").replace("_", " "),
            os.path.basename(item.file_path or ""),
            _seconds(item.timestamp_offset) if item.timestamp_offset is not None else "—",
            Paragraph(escape(item.sha256_hash or "Not recorded"), mono),
        ])
    if rows:
        grid(["ID", "Type", "Filename", "Offset", "SHA-256"], rows,
             [10 * mm, 24 * mm, 52 * mm, 16 * mm, CONTENT_WIDTH - 102 * mm])
    else:
        para("No evidence artifacts are recorded for this investigation.", small)

    # 6 ─────────────────────────────────────────────────────────────────────
    section("Evidence Integrity Re-Verification")
    keyvalues([
        ("Verified at", integrity["verified_at"]),
        ("Algorithm", integrity["algorithm"]),
        ("Artifacts checked", integrity["artifacts_checked"]),
        ("Result", integrity["summary"]),
        ("All digests re-verified", integrity["chain_intact"]),
        ("Method", integrity["method"]),
    ])
    problems = [item for item in integrity["artifacts"] if item["status"] != "verified"]
    if problems:
        story.append(Paragraph("Artifacts that did not verify", subheading))
        grid(["ID", "Type", "Status", "Detail"],
             [[item["evidence_id"], item["evidence_type"], item["status"], item["detail"]]
              for item in problems],
             [12 * mm, 28 * mm, 24 * mm, CONTENT_WIDTH - 64 * mm])
    para(integrity["limitations"], small)

    # 7 ─────────────────────────────────────────────────────────────────────
    section("Chain of Custody")
    scope = custody["custody_scope"]
    para(scope["definition"])
    para(scope["statement"])
    mine, theirs = scope["deeptrace_supplies"], scope["investigator_supplies"]
    grid(["What DeepTrace records", "What the investigating officer must supply"],
         [[mine[i] if i < len(mine) else "", theirs[i] if i < len(theirs) else ""]
          for i in range(max(len(mine), len(theirs)))],
         [CONTENT_WIDTH / 2, CONTENT_WIDTH / 2])
    story.append(Spacer(1, 2 * mm))
    para("The remainder of this section is the file half of that chain, as recorded by "
         "DeepTrace for this case.", small)

    story.append(Paragraph("Acquisition", subheading))
    acquisition = custody["acquisition"]
    counts = custody["counts"]
    keyvalues([
        ("Case reference", acquisition["case_reference"]),
        ("Item acquired", acquisition["submitted_filename"]),
        ("Acquired at", acquisition["received_at"]),
        ("Size at acquisition", f"{acquisition['file_size_bytes']} bytes"
                               if acquisition["file_size_bytes"] is not None else "Not recorded"),
        ("Acquisition digest", f"{acquisition['algorithm']}: {acquisition['sha256']}"),
        ("How the digest was bound", acquisition["hash_binding"]),
        ("Digests of derived files", acquisition["derived_hash_binding"]),
        ("How media type was decided", acquisition["type_determination"]),
        ("Stored filename", acquisition["filename_note"]),
        ("Time source", acquisition["clock_source"]),
        ("Artifacts in the chain", f"{counts['artifacts']} total — {counts['acquired']} acquired, "
                                   f"{counts['derived']} derived, "
                                   f"{counts['without_digest']} without a recorded digest"),
    ])

    story.append(Paragraph("Artifact lineage", subheading))
    if custody["artifact_ledger"]:
        grid(["ID", "Type", "Role in the chain", "Preserved at", "Digest"],
             [[entry["evidence_id"],
               (entry["evidence_type"] or "").replace("_", " "),
               entry["role"],
               entry["preserved_at"] or "Not recorded",
               "Recorded" if entry["digest_recorded"] else "Not recorded"]
              for entry in custody["artifact_ledger"]],
             [10 * mm, 24 * mm, 42 * mm, 40 * mm, CONTENT_WIDTH - 116 * mm])
        story.append(Spacer(1, 1.5 * mm))
        seen: set[str] = set()
        for entry in custody["artifact_ledger"]:
            key = entry["evidence_type"] or ""
            if key in seen:
                continue
            seen.add(key)
            para(f"{key.replace('_', ' ') or 'artifact'} — {entry['role_detail']}", small)
    else:
        para("No artifacts are recorded for this case, so no chain can be described.", small)
    para(custody["derivation_note"], small)

    story.append(Paragraph("Recorded chronology", subheading))
    chronology = custody["chronology"]
    if chronology:
        keyvalues([
            ("Events recorded", len(chronology)),
            ("First recorded event", f"{chronology[0]['recorded_at']} — {chronology[0]['description']}"),
            ("Most recent event", f"{chronology[-1]['recorded_at']} — {chronology[-1]['description']}"),
        ])
        para("The complete event sequence is listed in the Investigation Timeline section of "
             "this report.", small)
    else:
        para("No case events are recorded.", small)
    para(custody["chronology_note"], small)

    story.append(Paragraph("Where this custody record stops", subheading))
    grid(["Limitation", "What it means for this case"],
         [[Paragraph(f"<b>{escape(gap['gap'])}</b>", small), gap["detail"]]
          for gap in custody["custody_gaps"]],
         [62 * mm, CONTENT_WIDTH - 62 * mm])

    # 8 ─────────────────────────────────────────────────────────────────────
    section("What the Hash Proves and What the AI Analysis Establishes")
    para(custody["boundary_summary"])
    para("These are two different claims resting on two different kinds of evidence. Hashing is "
         "arithmetic over bytes and is either right or wrong. Model output is a statistical "
         "estimate with an error rate. Conflating them is the most common way a forensic "
         "conclusion is overstated, so they are separated here explicitly.", small)

    story.append(Paragraph(f"What {custody['acquisition']['algorithm']} hashing proves",
                           subheading))
    claims_table(custody["hashing_proves"], "Established by the digest")

    story.append(Paragraph(f"What {custody['acquisition']['algorithm']} hashing does not prove",
                           subheading))
    claims_table(custody["hashing_does_not_prove"], "Not established by the digest")

    story.append(Paragraph("What the AI analysis establishes", subheading))
    claims_table(custody["ai_establishes"], "Established by the analysis")

    story.append(Paragraph("What the AI analysis does not establish", subheading))
    claims_table(custody["ai_does_not_establish"], "Not established by the analysis")

    # 9 ─────────────────────────────────────────────────────────────────────
    section("Media Metadata and Technical Attributes")
    if metadata and metadata.get("status") == "completed":
        file_info = metadata.get("file") or {}
        keyvalues([
            ("Detected MIME type", file_info.get("mime_type")),
            ("Extension", file_info.get("extension")),
            ("Filesystem modified", file_info.get("modified_utc")),
        ])
        container = metadata.get("container") or {}
        if container:
            story.append(Paragraph("Container and streams", subheading))
            keyvalues([
                ("Format", container.get("container")),
                ("Video codec", container.get("video_codec")),
                ("Audio codec", container.get("audio_codec") or "No audio stream"),
                ("Resolution", container.get("resolution")),
                ("Frame rate", container.get("frame_rate")),
                ("Bit rate", container.get("bit_rate")),
                ("Encoder tag", container.get("encoder")),
                ("Creation tag", container.get("creation_time")),
            ])
        exif = metadata.get("exif") or {}
        if exif.get("exif_present"):
            story.append(Paragraph("EXIF fields present in the image", subheading))
            interesting = {k: v for k, v in exif.items()
                           if k not in {"exif_present", "note"} and v not in (None, "")}
            keyvalues(sorted(interesting.items())[:14])
        elif inv.media_type == "image":
            para("No EXIF metadata is present. Absence of EXIF is common — most platforms strip it "
                 "on upload — and is not itself an indicator of manipulation.", small)
        if metadata.get("observations"):
            story.append(Paragraph("Observations", subheading))
            for note in metadata["observations"]:
                para(f"• {note}", small)
    else:
        not_run(metadata, "Metadata extraction")

    # 10 ────────────────────────────────────────────────────────────────────
    section("Content Provenance and Located Sources")
    if provenance:
        keyvalues([
            ("Reader", provenance.get("method") or "c2pa-python"),
            ("Credentials found", provenance.get("credentials_found")),
            ("Status", provenance.get("status")),
        ])
        if provenance.get("credentials_found"):
            keyvalues([
                ("Claim generator", provenance.get("claim_generator")),
                ("Signature issuer", provenance.get("signature_issuer")),
                ("Signed on", provenance.get("signature_time")),
                ("Assertions", provenance.get("assertion_count")),
                ("Validation", provenance.get("validation_state")),
            ])
            para("Content Credentials describe what the signing tool asserted about this file. They "
                 "establish a signed provenance chain; they do not independently prove the content "
                 "is unmanipulated.", small)
        else:
            para("No Content Credentials are attached to this file. The overwhelming majority of "
                 "media in circulation carries none, so this is expected and is NOT treated as an "
                 "indicator of manipulation. It is excluded from the risk calculation entirely "
                 "rather than counted against the file.", small)
        _located_sources(provenance.get("external_search") or {})
    else:
        not_run(provenance, "Provenance inspection")

    # 11 ────────────────────────────────────────────────────────────────────
    section("Manipulation Analysis")
    if not not_run(deepfake, "Manipulation analysis"):
        keyvalues([
            ("Model", f"{deepfake.get('model_name')} {deepfake.get('model_version') or ''}".strip()),
            ("Model status", deepfake.get("model_status")),
            ("Manipulation signal", _score(deepfake.get("manipulation_signal"))),
            ("Decision threshold", _score(deepfake.get("threshold"), 2)),
            ("Frames analysed", deepfake.get("frames_analyzed")),
            ("Frames with a detected face", deepfake.get("frames_with_face")),
            ("Frames used for the aggregate", deepfake.get("frames_scored_for_aggregate")
                                              or deepfake.get("frames_analyzed")),
            ("Aggregate basis", deepfake.get("aggregate_basis")),
            ("Frames above threshold", deepfake.get("suspicious_frame_count")),
            ("Highest frame score", _score(deepfake.get("max_manipulation_signal"))),
            ("Lowest frame score", _score(deepfake.get("min_manipulation_signal"))),
            ("Score spread (std dev)", _score(deepfake.get("std_manipulation_signal"))),
        ])
        if deepfake.get("interpretation"):
            para(deepfake["interpretation"])
        frame_results = deepfake.get("frame_results") or []
        if len(frame_results) > 1:
            story.append(Paragraph("Per-frame scores", subheading))
            grid(["Timestamp", "Signal", "Face detected", "Face source", "Above threshold"],
                 [[_seconds(f.get("frame_timestamp_seconds")),
                   _score(f.get("manipulation_signal")),
                   f.get("face_detected"),
                   f.get("face_source") or "—",
                   f.get("suspicious")]
                  for f in frame_results],
                 [26 * mm, 22 * mm, 26 * mm, 30 * mm, CONTENT_WIDTH - 104 * mm])
        para(deepfake.get("disclaimer") or
             "This is a manipulation indicator, not a verdict.", small)

    # 12 ────────────────────────────────────────────────────────────────────
    section("Manipulation Localization")
    if not not_run(localization, "Localization"):
        keyvalues([
            ("Method", localization.get("method")),
            ("Suspicion threshold", _score(localization.get("threshold"), 2)),
            ("Summary", localization.get("summary")),
            ("Flagged windows", len(localization.get("suspicious_intervals") or [])),
        ])
        intervals = localization.get("suspicious_intervals") or []
        if intervals:
            story.append(Paragraph("Flagged time windows", subheading))
            grid(["Window", "Duration", "Samples in window", "Peak signal"],
                 [[i.get("label"),
                   f"{i.get('duration_seconds', 0):.2f} s",
                   i.get("sample_count"),
                   _score(i.get("peak_signal"))]
                  for i in intervals],
                 [42 * mm, 26 * mm, 34 * mm, CONTENT_WIDTH - 102 * mm])
        regions = localization.get("top_regions") or []
        if regions:
            story.append(Paragraph("Highest-scoring regions", subheading))
            grid(["Timestamp", "Signal", "Face region (x1,y1,x2,y2)", "Note"],
                 [[_seconds(r.get("timestamp_seconds")),
                   _score(r.get("manipulation_signal")),
                   ", ".join(str(v) for v in r["face_box_xyxy"]) if r.get("face_box_xyxy") else "Whole frame",
                   r.get("region_note")]
                  for r in regions[:10]],
                 [22 * mm, 20 * mm, 42 * mm, CONTENT_WIDTH - 84 * mm])
        overlays = localization.get("overlays") or []
        if overlays:
            story.append(Paragraph("Residual overlays for the highest-scoring frames", subheading))
            thumbnails([
                (overlay.get("overlay_path"),
                 f"{_seconds(overlay.get('timestamp_seconds'))} — signal "
                 f"{_score(overlay.get('manipulation_signal'))}")
                for overlay in overlays
            ])
        if localization.get("interpretation"):
            para(localization["interpretation"], small)

    # 13 ────────────────────────────────────────────────────────────────────
    section("Identity Comparison (Face)")
    if not not_run(identity_result, "Face comparison"):
        keyvalues([
            ("Reference identity", identity_result.get("reference_identity")),
            ("Model", identity_result.get("method")),
            ("Model status", identity_result.get("model_status")),
            ("Embedding dimensions", identity_result.get("embedding_dimensions")),
            ("Best similarity", _score(identity_result.get("best_similarity"))),
            ("Mean similarity", _score(identity_result.get("average_similarity"))),
            ("Same-person threshold", _score(identity_result.get("threshold"), 2)),
            ("Frames above threshold", f"{identity_result.get('above_threshold_frames')} of "
                                       f"{identity_result.get('frames_analyzed')}"),
            ("Frames with no detectable face", identity_result.get("faces_not_detected")),
        ])
        para(identity_result.get("interpretation"))
        details = identity_result.get("frame_details") or []
        if len(details) > 1:
            story.append(Paragraph("Per-frame comparison", subheading))
            grid(["Timestamp", "Face detected", "Cosine similarity"],
                 [[_seconds(d.get("timestamp_seconds")), d.get("face_detected"),
                   _score(d.get("similarity"))]
                  for d in details],
                 [34 * mm, 34 * mm, CONTENT_WIDTH - 68 * mm])
        para(identity_result.get("note") or "", small)

    # 14 ────────────────────────────────────────────────────────────────────
    section("Speaker Verification (Voice)")
    if not not_run(voice, "Speaker verification"):
        keyvalues([
            ("Reference identity", voice.get("reference_identity")),
            ("Model", voice.get("method")),
            ("Similarity score", _score(voice.get("voice_match_score"))),
            ("Decision threshold", _score(voice.get("threshold"), 2)),
            ("Verdict", (voice.get("verdict") or "").replace("_", " ")),
            ("Reference duration", f"{voice['reference_seconds']:.2f} s"
                                   if voice.get("reference_seconds") else None),
            ("Subject duration", f"{voice['subject_seconds']:.2f} s"
                                 if voice.get("subject_seconds") else None),
        ])
        para(voice.get("interpretation"))
        para(voice.get("note") or "", small)

    # 15 ────────────────────────────────────────────────────────────────────
    section("Audio Forensics")
    if not not_run(audio, "Audio forensics"):
        levels = audio.get("levels") or {}
        spectral = audio.get("spectral") or {}
        keyvalues([
            ("Method", audio.get("method")),
            ("Duration analysed", f"{audio['duration_seconds']:.2f} s"
                                  if audio.get("duration_seconds") else None),
            ("Sample rate", f"{audio.get('sample_rate')} Hz"),
            ("Peak level", f"{levels.get('peak_dbfs')} dBFS" if levels.get("peak_dbfs") is not None else None),
            ("RMS level", f"{levels.get('rms_dbfs')} dBFS" if levels.get("rms_dbfs") is not None else None),
            ("Crest factor", f"{levels.get('crest_factor_db')} dB"
                             if levels.get("crest_factor_db") is not None else None),
            ("Clipped samples", f"{levels.get('clipped_samples')} "
                                f"({(levels.get('clipping_ratio') or 0) * 100:.3f}%)"),
            ("Silence proportion", f"{(levels.get('silence_ratio') or 0) * 100:.1f}%"),
            ("Spectral centroid", f"{spectral.get('centroid_hz')} Hz"
                                  if spectral.get("centroid_hz") is not None else None),
            ("85% spectral rolloff", f"{spectral.get('rolloff_85_hz')} Hz"
                                     if spectral.get("rolloff_85_hz") is not None else None),
            ("Abrupt transitions", audio.get("discontinuity_count")),
            ("Transitions per minute", _score(audio.get("discontinuities_per_minute"), 2)),
            ("Editing indicator", _score(audio.get("editing_indicator"))),
        ])
        discontinuities = audio.get("discontinuities") or []
        if discontinuities:
            story.append(Paragraph("Detected abrupt loudness transitions", subheading))
            grid(["Timestamp", "Change (dB)", "Direction"],
                 [[_seconds(d.get("timestamp_seconds")), _score(d.get("delta_db"), 2),
                   d.get("direction")]
                  for d in discontinuities],
                 [34 * mm, 34 * mm, CONTENT_WIDTH - 68 * mm])
        for note in audio.get("observations") or []:
            para(f"• {note}", small)
        para(audio.get("interpretation") or "", small)

    # 16 ────────────────────────────────────────────────────────────────────
    section("Audio-Visual Consistency")
    if not not_run(consistency, "A/V consistency"):
        keyvalues([
            ("Method", consistency.get("method")),
            ("Alignment score", _score(consistency.get("consistency_score"))),
            ("Timestamps compared", consistency.get("samples_compared")),
            ("Aligned samples", consistency.get("aligned_samples")),
            ("Mismatched samples", consistency.get("mismatched_samples")),
            ("Stream duration agreement", (consistency.get("duration_agreement") or {}).get("summary")),
        ])
        mismatches = consistency.get("mismatches") or []
        if mismatches:
            story.append(Paragraph("Timestamps where audio and visual cues disagreed", subheading))
            grid(["Timestamp", "Observation"],
                 [[_seconds(m.get("timestamp_seconds")), m.get("observation")] for m in mismatches],
                 [28 * mm, CONTENT_WIDTH - 28 * mm])
        for note in consistency.get("observations") or []:
            para(f"• {note}", small)
        para(consistency.get("interpretation") or consistency.get("details") or "", small)

    # 17 ────────────────────────────────────────────────────────────────────
    section("Copy Tracing — Local Evidence Index")
    if not not_run(propagation, "Local copy tracing"):
        keyvalues([
            ("Method", propagation.get("method")),
            ("Scope", propagation.get("scope")),
            ("Cases indexed", propagation.get("cases_indexed")),
            ("Evidence rows compared", propagation.get("evidence_rows_compared")),
            ("Related cases found", propagation.get("match_count")),
            ("Byte-identical copies", propagation.get("exact_duplicate_cases")),
            ("Near-identical copies", propagation.get("near_duplicate_cases")),
            ("Visually similar", propagation.get("similar_content_cases")),
            ("Strongest match", propagation.get("best_similarity_label")),
        ])
        matches = propagation.get("matches") or []
        if matches:
            story.append(Paragraph("Related cases in this instance", subheading))
            grid(["Case", "Filename", "Relationship", "Similarity", "Basis"],
                 [[f"INV-{m['matched_investigation_id']:05d}"
                   if m.get("matched_investigation_id") is not None else "Unknown case",
                   m.get("matched_investigation_filename"),
                   (m.get("match_type") or "").replace("_", " "),
                   _score(m.get("similarity"), 4),
                   m.get("basis")]
                  for m in matches],
                 [22 * mm, 40 * mm, 26 * mm, 20 * mm, CONTENT_WIDTH - 108 * mm])
        if propagation.get("truncated_matches"):
            para(f"{propagation['truncated_matches']} further related case(s) were found but are not "
                 "listed individually.", small)
        para(propagation.get("interpretation") or "", small)

    # 18 ────────────────────────────────────────────────────────────────────
    section("Source Tracing")
    if trace_sources:
        grid(["Source", "Origin", "Retrieval", "Relationship to original", "SHA-256 of copy"],
             [[Paragraph(escape(s.get("source_url") or s.get("title") or "Investigator-supplied copy"),
                         small),
               (s.get("origin") or "").replace("_", " "),
               s.get("retrieval_status") + (f" — {s['retrieval_error']}" if s.get("retrieval_error") else ""),
               s.get("similarity_label") or "Not compared",
               Paragraph(escape((s.get("sha256") or "—")[:32] + ("…" if s.get("sha256") else "")), mono)]
              for s in trace_sources],
             [50 * mm, 22 * mm, 34 * mm, 30 * mm, CONTENT_WIDTH - 136 * mm])
    else:
        para("No external source was supplied for this case, so no copy was retrieved or compared. "
             "Where the media was found is investigator-supplied information; DeepTrace cannot "
             "discover it.")
    para("DeepTrace retrieves only specific public HTTPS URLs an investigator supplies, over a "
         "size-capped direct request. It performs no internet-wide search, accesses no private or "
         "authenticated API, bypasses no authentication, and circumvents no access control. Absence "
         "of a traced source says nothing about whether the media was distributed.", small)

    # 19 ────────────────────────────────────────────────────────────────────
    section("Explainable Risk Assessment")
    if risk:
        keyvalues([
            ("Overall risk score", _score(risk.get("overall_risk_score"))),
            ("Risk level", risk.get("risk_level")),
            ("Method", risk.get("method")),
            ("Signals available", risk.get("signals_used")),
            ("Signals excluded", risk.get("signals_excluded")),
        ])
        story.append(Paragraph("Signal-by-signal contribution", subheading))
        grid(["Signal", "Observed value", "Threshold", "Normalised", "Weight", "Contribution"],
             [[s.get("label"),
               f"{_score(s.get('raw_value'))} {s.get('raw_units') or ''}".strip(),
               _score(s.get("threshold"), 2) if s.get("threshold") is not None else "—",
               _score(s.get("normalized")),
               f"{s.get('effective_weight', 0) * 100:.1f}%",
               _score(s.get("contribution"))]
              for s in risk.get("signals") or []],
             [34 * mm, 32 * mm, 20 * mm, 22 * mm, 18 * mm, CONTENT_WIDTH - 126 * mm])
        story.append(Paragraph("What each signal contributed", subheading))
        for signal in risk.get("signals") or []:
            # Appended as a Paragraph rather than through para(), which escapes its
            # whole argument and would print the <b> tags literally.
            story.append(Paragraph(
                f"• <b>{escape(str(signal.get('label')))}</b> — {escape(str(signal.get('detail')))} "
                f"Source: {escape(str(signal.get('source_model') or 'n/a'))}.", small))
        excluded = risk.get("excluded_signals") or []
        if excluded:
            story.append(Paragraph("Signals excluded from the calculation", subheading))
            grid(["Signal", "Why it was excluded"],
                 [[e.get("label"), e.get("reason")] for e in excluded],
                 [40 * mm, CONTENT_WIDTH - 40 * mm])
            para("Excluded signals do not raise or lower the score. Weights are renormalised across "
                 "the signals that were actually available, so an unavailable module cannot silently "
                 "push the result in either direction.", small)
        para(risk.get("note") or "", small)
    else:
        not_run(risk, "Risk fusion")

    # 20 ────────────────────────────────────────────────────────────────────
    story.append(PageBreak())
    section("Investigation Timeline")
    events = sorted(inv.timeline_events, key=lambda e: (str(e.created_at or ""), e.id))
    if events:
        grid(["Recorded at (UTC)", "Event", "Detail"],
             [[event.created_at, (event.event_type or "").replace("_", " "), event.description]
              for event in events],
             [34 * mm, 34 * mm, CONTENT_WIDTH - 68 * mm])
        para(f"{len(events)} events recorded. Timestamps are written by the database at the moment "
             "each step completed; they are local records, not third-party timestamps.", small)
    else:
        para("No timeline events are recorded for this investigation.", small)

    # 21 ────────────────────────────────────────────────────────────────────
    section("Recommended Response and Reporting Routes")
    keyvalues([
        ("Response priority", guidance.get("priority")),
        ("Basis", f"Assessed risk level {guidance.get('risk_level')}"),
    ])
    story.append(Paragraph("Recommended actions", subheading))
    grid(["#", "Action", "Why (from this case)", "Who acts"],
         [[action.get("step"), action.get("action"), action.get("why"), action.get("who_acts")]
          for action in guidance.get("recommended_actions") or []],
         [8 * mm, 40 * mm, CONTENT_WIDTH - 82 * mm, 34 * mm])
    story.append(Paragraph("Evidence package available for export", subheading))
    for item in guidance.get("evidence_package") or []:
        para(f"• {item}", small)
    story.append(Paragraph("Available reporting routes", subheading))
    grid(["Route", "Detail", "Who acts"],
         [[route["route"], route["detail"], route["who_acts"]]
          for route in guidance.get("reporting_routes") or []],
         [40 * mm, CONTENT_WIDTH - 76 * mm, 36 * mm])
    para(guidance.get("deeptrace_boundary") or "", small)

    # 22 ────────────────────────────────────────────────────────────────────
    story.append(PageBreak())
    section("System Validation — Measured Accuracy and Robustness")
    story.append(Paragraph(
        "<b>This section is about DeepTrace, not about this case.</b> Nothing below changes any "
        "score, finding or conclusion in the preceding sections. It is here so that a reviewer "
        "reading a case score can see how often the detector was right on data where the answer "
        "was known, and how far its score moved when the same file was degraded — the two things "
        "needed to decide how much weight the case score deserves.", body))
    para(VALIDATION_BOUNDARY, small)
    para("Every figure below was read from a file written by DeepTrace's own validation harness on "
         "the machine that generated this report. No figure is a stored constant, none is copied "
         "from a published benchmark, and where a harness has not been run this section reports "
         "that instead of a number.", small)

    metrics_run = load_metrics()
    robustness_run = load_robustness()

    # ── labelled accuracy ────────────────────────────────────────────────
    story.append(Paragraph("Accuracy on labelled data — how often the detector is right",
                           subheading))
    detection = metrics_run.get("manipulation_detection") if metrics_run.get("available") else None
    if not isinstance(detection, dict):
        keyvalues([
            ("Status", "Not measured in this environment"),
            ("Reason", metrics_run.get("reason") or "No labelled evaluation result was stored."),
            ("How to produce it", METRICS_COMMAND),
        ])
        para("No precision, recall, F1 or false-positive rate is reported for this build. An "
             "unmeasured metric is not a passing metric, and no figure has been substituted for "
             "the missing measurement.", small)
    else:
        point = detection.get("operating_point") or {}
        class_counts = detection.get("class_counts") or {}
        env = metrics_run.get("environment") or {}
        keyvalues([
            ("Files scored", detection.get("evaluated")),
            ("Class balance", f"{class_counts.get('real', 0)} authentic, "
                              f"{class_counts.get('fake', 0)} manipulated"),
            ("Files skipped", detection.get("skipped_count")),
            ("Model actually loaded", detection.get("model")),
            ("Decision threshold", point.get("threshold", "Not recorded")),
            ("Evaluated at (UTC)", metrics_run.get("generated_at_utc")),
            ("Environment", f"Python {env.get('python')} on {env.get('platform')}, "
                            f"ffmpeg {'available' if env.get('ffmpeg_available') else 'unavailable'}"),
            ("Dataset fingerprint", detection.get("dataset_fingerprint")),
        ])

        if point:
            grid(["Metric", "Value", "95% CI (Wilson)", "What the number counts"],
                 [
                     ["Precision", _ratio(point.get("precision")),
                      _interval(point.get("precision_95_ci")),
                      "Of the files flagged as manipulated, the share that really were."],
                     ["Recall (sensitivity)", _ratio(point.get("recall_sensitivity")),
                      _interval(point.get("recall_95_ci")),
                      "Of the manipulated files, the share that were flagged."],
                     ["F1", _ratio(point.get("f1")), "—",
                      "Harmonic mean of precision and recall."],
                     ["Specificity", _ratio(point.get("specificity")), "—",
                      "Of the authentic files, the share correctly left unflagged."],
                     ["False-positive rate", _ratio(point.get("false_positive_rate")),
                      _interval(point.get("false_positive_rate_95_ci")),
                      point.get("false_positive_rate_definition")
                      or "The share of authentic files wrongly flagged as manipulated."],
                     ["False-negative rate", _ratio(point.get("false_negative_rate")),
                      _interval(point.get("false_negative_rate_95_ci")),
                      point.get("false_negative_rate_definition")
                      or "The share of manipulated files wrongly cleared as authentic."],
                     ["Accuracy", _ratio(point.get("accuracy")),
                      _interval(point.get("accuracy_95_ci")),
                      "Both classes decided correctly, over all files scored."],
                     ["ROC AUC", _ratio(detection.get("roc_auc")), "—",
                      "Threshold-free separation between the two classes. 0.5 is chance."],
                 ],
                 [30 * mm, 17 * mm, 27 * mm, CONTENT_WIDTH - 74 * mm])
            para(f"Measured at the same {point.get('threshold')} threshold the application itself "
                 "uses, so these figures describe the behaviour the interface actually shows rather "
                 "than a threshold chosen to flatter the result. The intervals are 95% Wilson "
                 "intervals — on a set this size they are wide, and quoting the point estimate "
                 "without them would overstate what was measured.", small)
            grid(["True positive", "False positive", "True negative", "False negative"],
                 [[point.get("true_positive"), point.get("false_positive"),
                   point.get("true_negative"), point.get("false_negative")]],
                 [CONTENT_WIDTH / 4] * 4)
        else:
            para("Only one class was present in the evaluated set, so precision, recall, F1 and the "
                 "false-positive rate have no denominator. They are reported as undefined rather "
                 "than as zero, which would read as a measured result of zero.", small)

        distribution = detection.get("score_distribution") or {}
        dist_rows = [
            [label, stats.get("count"), _ratio(stats.get("mean")), _ratio(stats.get("std")),
             _ratio(stats.get("min")), _ratio(stats.get("median")), _ratio(stats.get("max"))]
            for label, stats in (("Authentic", distribution.get("real")),
                                 ("Manipulated", distribution.get("fake")))
            if isinstance(stats, dict)
        ]
        if dist_rows:
            story.append(Paragraph("Score distribution by true class", subheading))
            grid(["True class", "n", "Mean", "Std", "Min", "Median", "Max"], dist_rows,
                 [30 * mm, 14 * mm] + [(CONTENT_WIDTH - 44 * mm) / 5] * 5)
            para("Printed because it shows what the summary metrics cannot: whether the two classes "
                 "separate at all. Overlapping means with a wide spread on one class is a weak "
                 "signal regardless of where the threshold is placed.", small)

        provenance_block = detection.get("dataset_provenance") or {}
        if provenance_block:
            story.append(Paragraph("Where the labels came from", subheading))
            keyvalues([
                ("Label source", provenance_block.get("label_source")),
                ("Declared by", provenance_block.get("declared_by")),
                ("Set built (UTC)", provenance_block.get("generated_at_utc")),
                ("Construction", provenance_block.get("construction")),
                ("Confound control", provenance_block.get("confound_control")),
            ])
            families = [entry for entry in (provenance_block.get("manipulation_families") or [])
                        if isinstance(entry, dict)]
            if families:
                grid(["Family", "Class", "Files", "What was done to the file"],
                     [[entry.get("name"), entry.get("class"), entry.get("count"),
                       entry.get("description")] for entry in families],
                     [28 * mm, 22 * mm, 13 * mm, CONTENT_WIDTH - 63 * mm])
            if provenance_block.get("manifest_mismatch"):
                story.append(Paragraph(
                    f"<b>Warning.</b> {escape(str(provenance_block['manifest_mismatch']))}", small))

        caveats = [text for text in (detection.get("caveats") or []) if text]
        if caveats:
            story.append(Paragraph("What these accuracy figures do not say", subheading))
            for text in caveats:
                para(f"• {text}", small)

    # ── robustness ───────────────────────────────────────────────────────
    story.append(Paragraph("Robustness under degradation — how far the score moves",
                           subheading))
    if not robustness_run.get("available"):
        keyvalues([
            ("Status", "Not measured in this environment"),
            ("Reason", robustness_run.get("reason") or "No robustness result was stored."),
            ("How to produce it", ROBUSTNESS_COMMAND),
        ])
        para("Nothing is reported about behaviour on compressed, re-uploaded or screen-recorded "
             "copies of a file. That gap is stated rather than left to be inferred from silence.",
             small)
    else:
        source = robustness_run.get("source") or {}
        keyvalues([
            ("Method", "The same file is scored before and after a real ffmpeg degradation, and the "
                       "two scores are compared. No labels are needed: the ground truth is that "
                       "both copies depict the same content."),
            ("Source media", f"{source.get('file_count', 0)} file(s) from "
                             f"{source.get('description', 'an unrecorded source')}"),
            ("Source fingerprint", source.get("fingerprint")),
            ("Decision threshold", robustness_run.get("threshold")),
            ("Evaluated at (UTC)", robustness_run.get("generated_at_utc")),
        ])

        relevant = {"video": "visual", "image": "visual", "audio": "audio"}.get(inv.media_type or "")
        for channel_key, channel_title in (("visual", "Image and video manipulation signal"),
                                           ("audio", "Audio editing indicator")):
            channel = robustness_run.get(channel_key) or {}
            overall = channel.get("overall") or {}
            bearing = (" — this is the channel that bears on the present case"
                       if channel_key == relevant else "")
            story.append(Paragraph(f"{channel_title}{bearing}", subheading))
            if not overall or not overall.get("paired_comparisons"):
                para("No paired comparison completed for this channel, so no robustness figure is "
                     "reported for it. That is an absence of measurement, not a passing result.",
                     small)
                continue
            grid(["Measure", "Value", "95% CI (Wilson)", "Reading"],
                 [
                     ["Decision agreement", _ratio(overall.get("decision_agreement")),
                      _interval(overall.get("decision_agreement_95_ci")),
                      f"Over {overall.get('paired_comparisons')} pairs, the share where the "
                      "degraded copy landed on the same side of the threshold as the original."],
                     ["Agreement, clear-cut only", _ratio(overall.get("clear_cut_agreement")),
                      _interval(overall.get("clear_cut_agreement_95_ci")),
                      f"Restricted to the {overall.get('clear_cut_comparisons')} file(s) whose "
                      f"original score was not borderline; "
                      f"{overall.get('borderline_baselines')} borderline baseline(s) excluded, "
                      "because a file scoring within 0.05 of the threshold flips under almost any "
                      "transform."],
                     ["Mean absolute score shift", _ratio(overall.get("mean_absolute_delta")),
                      "—",
                      "Mean change in the score itself. High agreement with a large shift still "
                      "means the score is unstable."],
                 ],
                 [38 * mm, 17 * mm, 27 * mm, CONTENT_WIDTH - 82 * mm])
            worst = overall.get("most_disruptive_transform") or {}
            if worst:
                story.append(Paragraph(
                    "Most disruptive transform for this channel: "
                    f"<b>{escape(str(worst.get('label')))}</b> "
                    f"({escape(str(worst.get('media_type')))}), mean shift "
                    f"{escape(_ratio(worst.get('mean_absolute_delta')))}, agreement "
                    f"{escape(_ratio(worst.get('decision_agreement')))}.", small))
            transforms = [entry for entry in (channel.get("per_transform") or [])
                          if isinstance(entry, dict)]
            if transforms:
                grid(["Transform", "Media", "Pairs", "Mean shift", "Agreement", "Direction of drift"],
                     [[entry.get("label"), entry.get("media_type"),
                       f"{entry.get('files_compared')}"
                       + (f" (+{entry.get('files_failed')} failed)"
                          if entry.get("files_failed") else ""),
                       _ratio(entry.get("mean_absolute_delta")),
                       _ratio(entry.get("decision_agreement")),
                       # The script itself says "no consistent direction" when the
                       # mean signed shift is within +/-0.005, so an absent value
                       # here can only mean no pair completed — not a null result.
                       entry.get("signed_delta_direction") or "not measured"]
                      for entry in transforms],
                     [CONTENT_WIDTH - 96 * mm, 16 * mm, 20 * mm, 20 * mm, 20 * mm, 20 * mm])
                para("Direction is the sign of the mean change, printed so that a systematic drift "
                     "stays visible even where the decision happened not to flip.", small)

        robustness_caveats = [text for text in (robustness_run.get("caveats") or []) if text]
        if robustness_caveats:
            story.append(Paragraph("What these robustness figures do not say", subheading))
            for text in robustness_caveats:
                para(f"• {text}", small)

    # 23 ────────────────────────────────────────────────────────────────────
    section("Methodology, Models, Limitations and Notice")
    story.append(Paragraph("Models and methods actually used in this case", subheading))
    model_rows = [
        ("Evidence integrity", "SHA-256 over the file as written to disk", integrity["algorithm"],
         "Completed"),
        ("Perceptual hashing", "64-bit pHash (ImageHash), Hamming distance", "Deterministic",
         "Completed" if inv.perceptual_hash or (propagation or {}).get("status") == "completed"
         else "Not applicable"),
    ]
    for label, payload in (
        ("Metadata extraction", metadata),
        ("Content provenance", provenance),
        ("Manipulation detection", deepfake),
        ("Manipulation localization", localization),
        ("Face comparison", identity_result),
        ("Speaker verification", voice),
        ("Audio forensics", audio),
        ("A/V consistency", consistency),
        ("Copy tracing", propagation),
    ):
        model_rows.append((
            label,
            (payload or {}).get("method") or "Did not run",
            (payload or {}).get("model_name") or (payload or {}).get("model_status") or "—",
            _status_label(payload),
        ))
    grid(["Stage", "Method", "Model / mode", "Status"],
         [list(row) for row in model_rows],
         [32 * mm, CONTENT_WIDTH - 100 * mm, 44 * mm, 24 * mm])

    story.append(Paragraph("Limitations that apply to this specific case", subheading))
    limitations = [
        "Model outputs are forensic indicators for expert review. They are not proof of "
        "manipulation, identity, authorship or criminal conduct.",
        "DeepTrace does not identify who created or uploaded the media.",
        "Hash-based preservation demonstrates the integrity of this local evidence store. It is "
        "not third-party timestamping or notarisation and does not by itself establish legal "
        "admissibility.",
    ]
    if inv.media_type == "video":
        limitations.append(
            f"Analysis sampled {inv.frames_extracted or 0} frame(s) across the video rather than "
            "every frame. Manipulation confined to unsampled segments would not be detected."
        )
    for label, payload in (
        ("Metadata extraction", metadata), ("Manipulation detection", deepfake),
        ("Manipulation localization", localization), ("Face comparison", identity_result),
        ("Speaker verification", voice), ("Audio forensics", audio),
        ("A/V consistency", consistency), ("Copy tracing", propagation),
    ):
        status = (payload or {}).get("status")
        if status in {"unavailable", "not_applicable"} or payload is None:
            reason = ((payload or {}).get("reason") or (payload or {}).get("details")
                      or "the module did not run")
            limitations.append(f"{label} did not contribute to this assessment: {reason}")
    if deepfake and deepfake.get("frames_with_face") == 0 and inv.media_type != "audio":
        limitations.append(
            "No face was detected in any analysed frame. The manipulation model is trained on "
            "cropped faces, so its score on whole frames is substantially less reliable."
        )
    if identity_result and identity_result.get("dimension_mismatch"):
        limitations.append(
            "The stored face template and the freshly computed embedding have different "
            "dimensions, so the identity comparison is not a valid face-identity match. "
            "Re-enroll the identity."
        )
    if not (provenance or {}).get("credentials_found"):
        limitations.append(
            "No C2PA Content Credentials were present, so provenance could not be independently "
            "confirmed. This is normal and was not counted against the file."
        )
    if not trace_sources:
        limitations.append(
            "No external source was traced, so nothing is known here about where or how widely the "
            "media was distributed."
        )
    for item in limitations:
        para(f"• {item}", small)

    story.append(Paragraph("What DeepTrace does not claim", subheading))
    for claim in (
        "It does not claim 100% or guaranteed deepfake detection.",
        "It does not perform internet-wide surveillance or monitoring.",
        "It does not identify the creator or uploader of media.",
        "It does not access private platforms, private APIs or authenticated endpoints, and it "
        "bypasses no access control.",
        "It does not guarantee legal admissibility of the preserved evidence.",
        "It does not treat an AI score as definitive proof of anything.",
    ):
        para(f"• {claim}", small)

    story.append(Spacer(1, 4 * mm))
    para("Prepared by DeepTrace — Team Algorythm (SIH26_28). This document is an evidence-preparation "
         "artifact for authorised investigative use. Findings require corroboration by a qualified "
         "examiner before any action is taken on them.", small)

    # ── Build ────────────────────────────────────────────────────────────────
    destination = report_path(inv.id)
    os.makedirs(os.path.dirname(destination), exist_ok=True)

    case_label = f"DeepTrace INV-{inv.id:05d} — {inv.filename or 'case'}"

    def decorate(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 6.6)
        canvas.setFillColor(colors.HexColor("#44586b"))
        canvas.drawString(15 * mm, A4[1] - 9 * mm, case_label[:110])
        canvas.drawRightString(A4[0] - 15 * mm, A4[1] - 9 * mm,
                               "Forensic indicators — not proof")
        canvas.setStrokeColor(GREY)
        canvas.setLineWidth(0.3)
        canvas.line(15 * mm, A4[1] - 11 * mm, A4[0] - 15 * mm, A4[1] - 11 * mm)
        canvas.line(15 * mm, 12 * mm, A4[0] - 15 * mm, 12 * mm)
        canvas.drawString(15 * mm, 8 * mm, f"Generated {integrity['verified_at']}")
        canvas.drawRightString(A4[0] - 15 * mm, 8 * mm, f"Page {document.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        destination, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"DeepTrace Forensic Incident Report INV-{inv.id:05d}",
        author="DeepTrace — Team Algorythm (SIH26_28)",
        subject="Digital impersonation forensic analysis and evidence preservation record",
    )
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return destination
