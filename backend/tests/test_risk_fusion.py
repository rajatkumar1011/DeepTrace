"""Explainable risk fusion.

The properties under test are the honesty guarantees, not particular scores:
weights renormalise over available signals only, unavailable signals are named
rather than defaulted to zero, absent Content Credentials never raise the score,
and the arithmetic can be reconstructed by hand from the payload.
"""

import pytest

from services.risk import FACE_THRESHOLD, MANIPULATION_THRESHOLD, fuse

DEEPFAKE = {"manipulation_signal": 0.90, "model_name": "DeepfakeBench Xception",
            "frames_analyzed": 12, "suspicious_frame_count": 9}
IDENTITY = {"best_similarity": 0.82, "reference_identity": "Test Subject",
            "model_name": "InceptionResnetV1"}
VOICE = {"status": "completed", "voice_match_score": 0.61, "model_name": "ECAPA-TDNN"}


def keys_of(entries):
    return {entry["key"] for entry in entries}


def test_effective_weights_sum_to_one_over_available_signals():
    result = fuse(deepfake=DEEPFAKE, identity=IDENTITY)
    assert result["signals_used"] == 2
    total = sum(signal["effective_weight"] for signal in result["signals"])
    assert total == pytest.approx(1.0, abs=0.001)


def test_score_can_be_reconstructed_by_hand_from_the_payload():
    """An investigator must be able to re-derive the number from the itemisation."""
    result = fuse(deepfake=DEEPFAKE, identity=IDENTITY, voice=VOICE)
    recomputed = sum(
        signal["effective_weight"] * signal["normalized"] for signal in result["signals"]
    )
    assert recomputed == pytest.approx(result["overall_risk_score"], abs=0.005)
    # And each itemised contribution is that product.
    for signal in result["signals"]:
        assert signal["contribution"] == pytest.approx(
            signal["effective_weight"] * signal["normalized"], abs=0.005
        )


def test_unavailable_signals_are_named_with_reasons_not_scored_as_zero():
    """A missing voice sample must not read as a voice mismatch."""
    result = fuse(deepfake=DEEPFAKE)

    assert "voice" in keys_of(result["excluded"])
    assert "identity" in keys_of(result["excluded"])
    for entry in result["excluded"]:
        assert entry["reason"].strip(), f"{entry['key']} was excluded without a reason"

    # With manipulation as the only signal, the score equals that signal exactly —
    # proof the excluded signals contributed no implicit zero.
    assert result["overall_risk_score"] == pytest.approx(DEEPFAKE["manipulation_signal"], abs=0.001)


def test_excluded_reason_is_propagated_from_the_module():
    reason = "No audio track could be decoded from this file."
    result = fuse(deepfake=DEEPFAKE, voice={"status": "unavailable", "reason": reason})
    voice_entry = next(entry for entry in result["excluded"] if entry["key"] == "voice")
    assert voice_entry["reason"] == reason


def test_absent_content_credentials_do_not_raise_the_score():
    """Most legitimate media carries no C2PA manifest; absence must be neutral."""
    without = fuse(deepfake=DEEPFAKE, identity=IDENTITY, provenance={"credentials_found": False})
    silent = fuse(deepfake=DEEPFAKE, identity=IDENTITY)

    assert without["overall_risk_score"] == silent["overall_risk_score"]
    provenance = next(entry for entry in without["excluded"] if entry["key"] == "provenance")
    assert "NOT" in provenance["reason"] and "manipulation" in provenance["reason"]


def test_present_content_credentials_reduce_the_score():
    with_credentials = fuse(deepfake=DEEPFAKE, identity=IDENTITY,
                            provenance={"credentials_found": True, "claim_generator": "TestCam"})
    without = fuse(deepfake=DEEPFAKE, identity=IDENTITY)

    assert with_credentials["overall_risk_score"] < without["overall_risk_score"]
    provenance = next(s for s in with_credentials["signals"] if s["key"] == "provenance")
    assert provenance["normalized"] == 0.0


def test_no_signals_yields_no_assessment_rather_than_zero_risk():
    result = fuse()
    assert result["signals_used"] == 0
    assert result["overall_risk_score"] == 0.0
    assert "No forensic signal could be computed" in result["explanation"]
    assert len(result["excluded"]) >= 6


def test_identity_below_threshold_is_described_as_weakening_the_case():
    result = fuse(deepfake=DEEPFAKE, identity={"best_similarity": 0.31,
                                               "reference_identity": "Test Subject"})
    identity_signal = next(s for s in result["signals"] if s["key"] == "identity")
    assert "below" in identity_signal["detail"]
    assert identity_signal["normalized"] < 0.5, "sub-threshold similarity must map below the midpoint"


def test_threshold_anchoring_places_the_published_threshold_at_the_midpoint():
    result = fuse(identity={"best_similarity": FACE_THRESHOLD})
    identity_signal = next(s for s in result["signals"] if s["key"] == "identity")
    assert identity_signal["normalized"] == pytest.approx(0.5, abs=0.001)


def test_risk_bands_are_monotonic_in_the_score():
    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    previous = -1
    for value in (0.05, 0.30, 0.60, 0.90):
        band = fuse(deepfake={"manipulation_signal": value})["risk_level"]
        assert order[band] >= previous
        previous = order[band]


def test_score_stays_within_bounds():
    for value in (0.0, 0.5, 1.0):
        result = fuse(deepfake={"manipulation_signal": value}, identity={"best_similarity": value})
        assert 0.0 <= result["overall_risk_score"] <= 1.0


def test_disclaimer_and_thresholds_travel_with_the_payload():
    """§27: the result must never present itself as proof."""
    result = fuse(deepfake=DEEPFAKE)
    disclaimer = result["disclaimer"].lower()
    assert "not proof" in disclaimer
    assert "not a legal determination" in disclaimer
    assert result["thresholds"]["manipulation_probability"] == MANIPULATION_THRESHOLD
    assert "renormalised" in result["formula"]


def test_explanation_reports_the_dominant_contributor():
    result = fuse(deepfake=DEEPFAKE, identity=IDENTITY, voice=VOICE)
    assert "largest single contribution" in result["explanation"]
    assert "forensic indicators" in result["explanation"]
