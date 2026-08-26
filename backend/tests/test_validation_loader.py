"""The validation-artifact loader.

These assertions exist because of one rule the project cannot break: DeepTrace
must never present a number it did not measure. Both surfaces that report
accuracy — /api/benchmark and the PDF report — read through this loader, so the
absence path is the one that has to be provably honest. A loader that returned an
empty metrics dict instead of a reason would let a renderer print 0.000 where
"not measured" belongs, and nothing downstream could tell the difference.
"""

import json
import os

import pytest

from services import validation


@pytest.fixture
def benchmark_dir(tmp_path, monkeypatch):
    """Point the loader at an empty throwaway directory."""
    monkeypatch.setattr(validation, "BENCHMARK_DIR", str(tmp_path))
    return tmp_path


def _write(directory, name, payload):
    path = os.path.join(str(directory), name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return path


def test_absent_metrics_report_a_reason_and_no_figures(benchmark_dir):
    result = validation.load_metrics()

    assert result["available"] is False
    assert "scripts/benchmark.py" in result["reason"]
    # The absence must not be dressed up as an empty result: a caller that
    # reached for a metric here has to find nothing at all, not a zero.
    assert "manipulation_detection" not in result
    assert "operating_point" not in result


def test_absent_robustness_reports_a_reason_and_no_figures(benchmark_dir):
    result = validation.load_robustness()

    assert result["available"] is False
    assert "scripts/robustness.py" in result["reason"]
    assert "visual" not in result
    assert "audio" not in result


def test_stored_run_is_returned_verbatim(benchmark_dir):
    _write(benchmark_dir, validation.METRICS_FILENAME,
           {"generated_at_utc": "2026-01-01T00:00:00+00:00",
            "manipulation_detection": {"evaluated": 24}})

    result = validation.load_metrics()

    assert result["available"] is True
    assert result["generated_at_utc"] == "2026-01-01T00:00:00+00:00"
    assert result["manipulation_detection"]["evaluated"] == 24


def test_unreadable_file_is_reported_not_raised(benchmark_dir):
    path = os.path.join(str(benchmark_dir), validation.ROBUSTNESS_FILENAME)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("{not json")

    result = validation.load_robustness()

    assert result["available"] is False
    assert "could not be read" in result["reason"]


def test_non_object_payload_is_refused(benchmark_dir):
    _write(benchmark_dir, validation.METRICS_FILENAME, [1, 2, 3])

    result = validation.load_metrics()

    assert result["available"] is False
    assert "not a validation record" in result["reason"]


def test_file_cannot_claim_its_own_availability(benchmark_dir):
    """``available`` describes this machine, so the loader's verdict wins.

    A stored artifact carrying ``available: false`` would otherwise make a run
    that is present on disk report itself as missing, and one carrying
    ``available: true`` would survive a future change to the absence path.
    """
    _write(benchmark_dir, validation.METRICS_FILENAME,
           {"available": False, "manipulation_detection": {"evaluated": 7}})

    result = validation.load_metrics()

    assert result["available"] is True
    assert result["manipulation_detection"]["evaluated"] == 7


def test_the_two_runs_are_independent(benchmark_dir):
    """One harness having run says nothing about the other."""
    _write(benchmark_dir, validation.ROBUSTNESS_FILENAME, {"threshold": 0.5})

    assert validation.load_robustness()["available"] is True
    assert validation.load_metrics()["available"] is False


def test_boundary_text_separates_the_two_claims():
    """The boundary sentence is the one piece of copy both surfaces must share."""
    assert "how often the detector is right" in validation.BOUNDARY
    assert "how much its score moves" in validation.BOUNDARY
