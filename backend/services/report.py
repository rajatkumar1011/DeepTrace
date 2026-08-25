"""Forensic incident report generation.

Twenty sections, every value read from what the pipeline actually recorded. A
module that did not run is printed as not-run, with the reason it gave — no
section is filled with a plausible-looking placeholder, and the limitations
section is assembled from the observed module statuses rather than a fixed list.
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


def _status_label(payload: dict | None) -> str:
    if not payload:
        return "Not run"
    return STATUS_LABELS.get(payload.get("status"), _text(payload.get("status")))


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
        ("Chain intact", integrity["chain_intact"]),
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

    # 8 ─────────────────────────────────────────────────────────────────────
    section("Content Provenance (C2PA Content Credentials)")
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
    else:
        not_run(provenance, "Provenance inspection")

    # 9 ─────────────────────────────────────────────────────────────────────
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

    # 10 ────────────────────────────────────────────────────────────────────
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

    # 11 ────────────────────────────────────────────────────────────────────
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

    # 12 ────────────────────────────────────────────────────────────────────
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

    # 13 ────────────────────────────────────────────────────────────────────
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

    # 14 ────────────────────────────────────────────────────────────────────
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

    # 15 ────────────────────────────────────────────────────────────────────
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

    # 16 ────────────────────────────────────────────────────────────────────
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

    # 17 ────────────────────────────────────────────────────────────────────
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
            para(f"• <b>{escape(str(signal.get('label')))}</b> — {escape(str(signal.get('detail')))} "
                 f"Source: {escape(str(signal.get('source_model') or 'n/a'))}.", small)
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

    # 18 ────────────────────────────────────────────────────────────────────
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

    # 19 ────────────────────────────────────────────────────────────────────
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

    # 20 ────────────────────────────────────────────────────────────────────
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
