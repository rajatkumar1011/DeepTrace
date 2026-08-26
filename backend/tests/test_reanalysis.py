"""Re-analysis discards the previous run's output, and only that.

Re-running is destructive by design — module results are recomputed from the
preserved original every time. What matters is the boundary: the original
submission and any retrieved external copy must survive untouched, and the
previous run's PDF must not survive at all, because a report describing results
that no longer exist is the one stale artifact that could be filed as current.
"""

import os

import pytest

from paths import EVIDENCE_DIR, FRAMES_DIR, REPORTS_DIR, report_path


@pytest.fixture
def case(client):
    """A completed-looking case with one original, one derived artifact and a report.

    ``client`` is requested so the app and its tables exist before this touches
    the session factory.
    """
    import main
    from database import SessionLocal
    from models.schema import AnalysisResult, Evidence, Investigation

    os.makedirs(FRAMES_DIR, exist_ok=True)
    os.makedirs(REPORTS_DIR, exist_ok=True)

    db = SessionLocal()
    original = os.path.join(EVIDENCE_DIR, "test_original_reset.bin")
    with open(original, "wb") as handle:
        handle.write(b"the submitted bytes")

    inv = Investigation(
        filename="reset.bin", file_path=original, file_size_bytes=19,
        sha256_hash="0" * 64, media_type="image", status="completed",
        overall_risk_score=0.61, risk_level="HIGH", frames_extracted=3,
    )
    db.add(inv)
    db.commit()

    frame = os.path.join(FRAMES_DIR, f"test_reset_{inv.id}.jpg")
    with open(frame, "wb") as handle:
        handle.write(b"a sampled frame")

    db.add(Evidence(investigation_id=inv.id, evidence_type="original",
                    file_path=original, sha256_hash="0" * 64))
    db.add(Evidence(investigation_id=inv.id, evidence_type="frame",
                    file_path=frame, sha256_hash="1" * 64))
    db.add(AnalysisResult(investigation_id=inv.id, module_name="manipulation",
                          score=0.7, status="completed", result_data={"stale": True}))
    pdf = report_path(inv.id)
    with open(pdf, "wb") as handle:
        handle.write(b"%PDF-1.4 previous run")
    db.commit()

    yield main, db, inv, {"original": original, "frame": frame, "pdf": pdf}

    db.close()
    for path in (original, frame, pdf):
        try:
            os.remove(path)
        except OSError:
            pass


def test_reset_discards_module_results_and_derived_artifacts(case):
    from models.schema import AnalysisResult, Evidence

    main, db, inv, files = case
    cleared, report_discarded = main.reset_derived_state(db, inv)

    assert cleared == 1
    assert report_discarded is True
    assert db.query(AnalysisResult).filter(AnalysisResult.investigation_id == inv.id).count() == 0
    assert not os.path.exists(files["frame"])

    kinds = {row.evidence_type for row in db.query(Evidence)
             .filter(Evidence.investigation_id == inv.id).all()}
    assert kinds == {"original"}


def test_reset_never_touches_the_original_submission(case):
    main, db, inv, files = case
    main.reset_derived_state(db, inv)

    assert os.path.isfile(files["original"])
    with open(files["original"], "rb") as handle:
        assert handle.read() == b"the submitted bytes"
    assert inv.sha256_hash == "0" * 64


def test_reset_removes_the_superseded_report(case):
    """The old PDF must not remain downloadable while the new run has no results."""
    main, db, inv, files = case
    main.reset_derived_state(db, inv)

    assert not os.path.exists(files["pdf"])


def test_reset_clears_the_previous_risk_verdict(case):
    """A stale score is worse than no score: it reads as the current finding."""
    main, db, inv, _ = case
    main.reset_derived_state(db, inv)

    assert inv.overall_risk_score is None
    assert inv.risk_level is None
    assert inv.frames_extracted == 0


def test_reset_on_a_case_without_a_report_reports_nothing_discarded(case):
    main, db, inv, files = case
    os.remove(files["pdf"])

    _, report_discarded = main.reset_derived_state(db, inv)
    assert report_discarded is False


def test_reanalysis_is_refused_while_a_run_is_in_flight(client):
    """Two concurrent runs would interleave writes to the same derived paths."""
    from database import SessionLocal
    from models.schema import Investigation

    db = SessionLocal()
    inv = Investigation(filename="busy.bin", file_path="/nonexistent/busy.bin",
                        media_type="image", status="analyzing")
    db.add(inv)
    db.commit()
    investigation_id = inv.id
    db.close()

    response = client.post(f"/api/investigation/{investigation_id}/analyze")
    assert response.status_code == 409
