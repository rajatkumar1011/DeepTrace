import os
from html import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _p(value, style):
    return Paragraph(escape(str(value if value is not None else "N/A")), style)


def _latest(results):
    latest = {}
    for result in results:
        latest[result.module_name] = result
    return latest


def generate_report(investigation_id: int, db_session) -> str:
    from models.schema import Investigation

    inv = db_session.query(Investigation).filter(Investigation.id == investigation_id).first()
    if not inv:
        return None

    reports_dir = os.path.join("data", "reports")
    os.makedirs(reports_dir, exist_ok=True)
    file_path = os.path.join(reports_dir, f"DeepTrace_Report_INV{investigation_id}.pdf")
    styles = getSampleStyleSheet()
    body = ParagraphStyle("ReportBody", parent=styles["BodyText"], fontSize=8.5, leading=11)
    small = ParagraphStyle("ReportSmall", parent=body, fontSize=7.5, leading=9)
    heading = ParagraphStyle("ReportHeading", parent=styles["Heading2"], spaceBefore=12, spaceAfter=6)
    title = ParagraphStyle("ReportTitle", parent=styles["Title"], fontSize=18, leading=22, textColor=colors.HexColor("#0b3954"))
    elements = [
        Paragraph("DeepTrace Forensic Incident Report", title),
        Spacer(1, 8),
        Paragraph("Analytical aid and evidence-preparation artifact. Model outputs are not by themselves proof of identity, manipulation, authorship, or criminal conduct.", body),
        Spacer(1, 14),
    ]

    def section(number, name):
        elements.append(Paragraph(f"{number}. {name}", heading))

    def key_values(rows):
        table = Table([[_p(key, body), _p(value, small)] for key, value in rows], colWidths=[1.45 * inch, 5.65 * inch])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e8eef2")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#9aaab5")),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(table)

    section(1, "Investigation Details")
    key_values([
        ("Investigation ID", inv.id), ("Original filename", inv.filename),
        ("File type", inv.media_type), ("File size", f"{inv.file_size_bytes} bytes"),
        ("Date/time", inv.created_at), ("Status", inv.status),
    ])
    section(2, "Evidence Integrity")
    key_values([
        ("Evidence integrity hash", inv.sha256_hash),
        ("Hash provenance", "Hash calculated from original uploaded file."),
        ("Preserved artifacts", f"{len(inv.evidence_items)} evidence item(s); original upload is retained."),
    ])

    latest = _latest(inv.analysis_results)
    labels = {"deepfake": "Manipulation signal", "identity": "Visual similarity signal", "voice": "Voice", "consistency": "A/V consistency", "provenance": "Provenance", "similarity": "Local similarity"}
    section(3, "Analysis Findings")
    rows = [[_p("Module", body), _p("Result", body), _p("Method / status", body)]]
    for name, label in labels.items():
        result = latest.get(name)
        if result:
            data = result.result_data or {}
            score = "Unavailable" if result.score is None else f"{result.score:.3f}"
            rows.append([_p(label, small), _p(score, small), _p(f"{data.get('method', 'Recorded forensic signal')}. {data.get('status', 'Completed')}", small)])
    table = Table(rows, colWidths=[1.55 * inch, 0.8 * inch, 4.75 * inch], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b3954")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#9aaab5")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    elements.append(table)

    section(4, "Localization")
    deepfake = latest.get("deepfake")
    frames = (deepfake.result_data or {}).get("frame_results", []) if deepfake else []
    suspicious = [frame for frame in frames if frame.get("suspicious")]
    key_values([
        ("Frames extracted", inv.frames_extracted or 0),
        ("Suspicious timestamps", ", ".join(str(frame.get("frame_path", "")) for frame in suspicious) or "None identified by the available signal"),
        ("Video metadata", f"{inv.resolution or 'N/A'}, {inv.fps or 'N/A'} fps, {inv.duration_seconds or 'N/A'} seconds"),
    ])
    section(5, "Provenance")
    provenance = latest.get("provenance")
    provenance_data = provenance.result_data if provenance else {}
    key_values([("C2PA status", provenance_data.get("status", "C2PA verification unavailable in this prototype.")), ("Content Credentials", "No Content Credentials were independently verified.")])
    section(6, "Similarity Findings")
    similarity_data = (latest.get("similarity").result_data if latest.get("similarity") else {}) or {}
    key_values([("Indexed scope", "Local indexed evidence only; this is not universal internet crawling."), ("Result", similarity_data.get("status", "No local match")), ("Matches", len(similarity_data.get("matches", [])))])
    section(7, "Risk Assessment")
    risk_data = (latest.get("risk_fusion").result_data if latest.get("risk_fusion") else {}) or {}
    key_values([("Risk assessment", inv.risk_level or "PENDING"), ("Risk score", inv.overall_risk_score if inv.overall_risk_score is not None else "N/A"), ("Contributing evidence", risk_data.get("contributors", "N/A")), ("Interpretation", "Risk score is an analytical aid, not proof of manipulation or identity.")])
    section(8, "Investigation Timeline")
    timeline_rows = [[_p("Event", body), _p("Description", body), _p("Date/time", body)]]
    for event in sorted(inv.timeline_events, key=lambda item: str(item.created_at or "")):
        timeline_rows.append([_p(event.event_type, small), _p(event.description, small), _p(event.created_at, small)])
    timeline = Table(timeline_rows, colWidths=[1.55 * inch, 3.75 * inch, 1.8 * inch], repeatRows=1)
    timeline.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b3954")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#9aaab5")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    elements.append(timeline)
    section(9, "Methodology")
    elements.append(Paragraph("DeepTrace calculates a SHA-256 hash for the original upload, extracts available metadata and sampled frames, preserves frame hashes, compares against a selected protected identity when available, searches local indexed evidence, and fuses only available signals using a documented weighted calculation.", body))
    section(10, "Limitations")
    elements.append(Paragraph("Advanced ML models may be unavailable on this machine. Lightweight fallback signals are not trained deepfake detection, guaranteed identity verification, attribution, or criminal evidence. Provenance/C2PA verification is unavailable in this prototype. Similarity tracing is limited to supported local/indexed sources and does not represent the entire internet.", body))

    doc = SimpleDocTemplate(file_path, pagesize=letter, rightMargin=0.55 * inch, leftMargin=0.55 * inch, topMargin=0.55 * inch, bottomMargin=0.55 * inch)
    doc.build(elements)
    return file_path
