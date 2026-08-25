"""Benchmark statistics.

Every case here has a hand-computable answer, so a regression in the metric code
is caught without needing a dataset. The dataset-absent behaviour is asserted too:
DeepTrace must keep reporting no benchmark rather than inventing one.
"""

import importlib.util
import os

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "deeptrace_benchmark",
    os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "benchmark.py"),
)
benchmark = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(benchmark)


# ── Confusion matrix ─────────────────────────────────────────────────────────

def test_perfect_separation():
    scores = [0.1, 0.2, 0.8, 0.9]
    labels = [0, 0, 1, 1]
    result = benchmark.confusion_at(scores, labels, 0.5)

    assert (result["true_positive"], result["false_positive"]) == (2, 0)
    assert (result["true_negative"], result["false_negative"]) == (2, 0)
    assert result["accuracy"] == 1.0
    assert result["precision"] == 1.0
    assert result["recall_sensitivity"] == 1.0
    assert result["specificity"] == 1.0
    assert result["f1"] == 1.0


def test_hand_computed_mixed_case():
    # Two of each class; one false positive and one false negative by construction.
    scores = [0.9, 0.1, 0.8, 0.2]
    labels = [0, 0, 1, 1]
    result = benchmark.confusion_at(scores, labels, 0.5)

    assert (result["true_positive"], result["false_positive"]) == (1, 1)
    assert (result["true_negative"], result["false_negative"]) == (1, 1)
    assert result["accuracy"] == 0.5          # 2 correct of 4
    assert result["precision"] == 0.5         # 1 / (1 + 1)
    assert result["recall_sensitivity"] == 0.5
    assert result["f1"] == 0.5


def test_threshold_is_inclusive_at_the_boundary():
    """A score exactly at the threshold counts as flagged, matching the app."""
    result = benchmark.confusion_at([0.5], [1], 0.5)
    assert result["true_positive"] == 1


def test_undefined_rates_are_null_not_zero():
    """No positive predictions means precision is undefined, not 0.0."""
    result = benchmark.confusion_at([0.1, 0.2], [0, 0], 0.5)
    assert result["precision"] is None
    assert result["recall_sensitivity"] is None
    assert result["f1"] is None
    assert result["accuracy"] == 1.0


# ── ROC AUC ──────────────────────────────────────────────────────────────────

def test_auc_perfect_and_inverted():
    assert benchmark.roc_auc([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1]) == 1.0
    assert benchmark.roc_auc([0.9, 0.8, 0.2, 0.1], [0, 0, 1, 1]) == 0.0


def test_auc_of_all_tied_scores_is_one_half():
    """Complete ties carry no ranking information."""
    assert benchmark.roc_auc([0.5] * 4, [0, 0, 1, 1]) == 0.5


def test_auc_handles_partial_ties():
    # One positive tied with one negative at 0.5, one clean pair either side.
    assert benchmark.roc_auc([0.1, 0.5, 0.5, 0.9], [0, 0, 1, 1]) == pytest.approx(0.875, abs=0.001)


def test_auc_is_none_when_a_class_is_absent():
    assert benchmark.roc_auc([0.1, 0.9], [1, 1]) is None
    assert benchmark.roc_auc([0.1, 0.9], [0, 0]) is None


# ── Wilson interval ──────────────────────────────────────────────────────────

def test_wilson_interval_brackets_the_estimate():
    low, high = benchmark.wilson_interval(5, 10)
    assert low < 0.5 < high


def test_wilson_interval_is_wide_for_small_samples_and_narrow_for_large():
    small = benchmark.wilson_interval(1, 2)
    large = benchmark.wilson_interval(500, 1000)
    assert (small[1] - small[0]) > (large[1] - large[0])
    # A 2-sample result must not look precise.
    assert (small[1] - small[0]) > 0.7


def test_wilson_interval_stays_within_zero_and_one():
    for successes, total in ((0, 5), (5, 5), (1, 1), (0, 1)):
        low, high = benchmark.wilson_interval(successes, total)
        assert 0.0 <= low <= high <= 1.0


def test_wilson_interval_of_perfect_score_does_not_claim_certainty():
    """3/3 correct is not proof of 100% accuracy."""
    low, _ = benchmark.wilson_interval(3, 3)
    assert low < 1.0


def test_wilson_interval_undefined_for_no_samples():
    assert benchmark.wilson_interval(0, 0) is None


# ── Distribution ─────────────────────────────────────────────────────────────

def test_distribution_of_known_values():
    result = benchmark.distribution([0.0, 0.5, 1.0])
    assert result["count"] == 3
    assert result["mean"] == 0.5
    assert result["min"] == 0.0
    assert result["max"] == 1.0
    assert result["median"] == 0.5


def test_distribution_of_nothing_is_none():
    assert benchmark.distribution([]) is None


# ── Dataset handling ─────────────────────────────────────────────────────────

def test_missing_dataset_produces_no_metrics(tmp_path, monkeypatch):
    """§34: with no labelled data, the script must write nothing at all."""
    monkeypatch.setattr(benchmark, "DATASET_DIR", str(tmp_path / "absent"))
    assert benchmark.evaluate_manipulation(0.5, 4) is None


def test_collect_ignores_non_media_files(tmp_path):
    (tmp_path / "notes.txt").write_text("not media")
    (tmp_path / "labels.csv").write_text("a,b")
    (tmp_path / "clip.mp4").write_bytes(b"\x00")
    (tmp_path / "photo.JPG").write_bytes(b"\x00")

    names = [os.path.basename(path) for path in benchmark.collect(str(tmp_path))]
    assert sorted(names) == ["clip.mp4", "photo.JPG"]


def test_dataset_fingerprint_changes_with_contents(tmp_path):
    """Results must not be silently reusable across different datasets."""
    first = tmp_path / "a.jpg"
    first.write_bytes(b"\x00" * 10)
    original = benchmark.dataset_fingerprint([str(first)])

    first.write_bytes(b"\x00" * 20)
    assert benchmark.dataset_fingerprint([str(first)]) != original


def test_single_class_dataset_reports_undefined_metrics():
    """One class cannot support accuracy or AUC; they must be null with a caveat."""
    scores, labels = [0.9, 0.8], [1, 1]
    assert benchmark.roc_auc(scores, labels) is None


def test_unsupported_extension_is_skipped_with_a_reason(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("x")
    outcome = benchmark.score_file(str(path), frames=4)
    assert outcome["ok"] is False
    assert "Unsupported" in outcome["reason"]
