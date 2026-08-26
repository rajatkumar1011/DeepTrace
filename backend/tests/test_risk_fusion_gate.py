"""What a module is allowed to contribute to the risk score.

The rule these protect: a module that produced a number may still have
established that the number does not describe this media. A speaker cosine from a
half-second clip, an audio/video alignment figure from B-roll — both are real
measurements of the wrong thing. The module that made the measurement is the only
place that can know this, so it says so with ``excluded_from_risk``, and fusion
must honour it.

That flag existed before these tests and was read by nothing: three modules set
it and the fusion ignored it, deciding on ``status == "completed"`` alone. So an
explicitly inconclusive voice comparison was still weighted at 0.12 and normalised
against ECAPA's threshold as though it were a decision. These assertions are what
turn the flag from a comment into a contract.
"""

import pytest

from services import risk
from services.risk import WEIGHTS


def _voice(**overrides) -> dict:
    payload = {
        "status": "completed",
        "voice_match_score": 0.40,
        "interpretation": "Speaker similarity 0.400 is above the threshold.",
        "model_name": "ECAPA-TDNN / VoxCeleb",
        "excluded_from_risk": False,
    }
    payload.update(overrides)
    return payload


def _consistency(**overrides) -> dict:
    payload = {
        "status": "completed",
        "consistency_score": 0.30,
        "details": "Alignment is the share of sampled timestamps that agree.",
        "excluded_from_risk": False,
    }
    payload.update(overrides)
    return payload


def _assess(**modules):
    return risk.fuse(**modules)


def _keys(entries) -> set:
    return {entry["key"] for entry in entries}


# ── the gate itself ──────────────────────────────────────────────────────────

def test_a_completed_module_that_withdraws_itself_is_not_weighted():
    included = _assess(voice=_voice())
    withdrawn = _assess(voice=_voice(excluded_from_risk=True,
                                    exclusion_reason="The clip is 0.30s, below the 1.0s floor."))

    assert "voice" in _keys(included["signals"])
    assert "voice" not in _keys(withdrawn["signals"]), (
        "an inconclusive voice comparison was still given a weight in fusion"
    )
    assert "voice" in _keys(withdrawn["excluded"])


def test_the_module_s_own_reason_is_the_one_reported():
    reason = "The clip is 0.30s, below the 1.0s floor DeepTrace requires."
    result = _assess(voice=_voice(excluded_from_risk=True, exclusion_reason=reason))

    entry = next(item for item in result["excluded"] if item["key"] == "voice")
    assert entry["reason"] == reason, "fusion substituted its own wording for the module's"


def test_withdrawing_changes_the_score_rather_than_being_cosmetic():
    """If the flag were decorative both scores would be identical."""
    included = _assess(voice=_voice(voice_match_score=0.95))
    withdrawn = _assess(voice=_voice(voice_match_score=0.95, excluded_from_risk=True))

    assert included["overall_risk_score"] != withdrawn["overall_risk_score"]
    assert withdrawn["overall_risk_score"] == 0.0, (
        "with every signal withdrawn the score must be 0, not a partial sum"
    )
    assert withdrawn["signals_used"] == 0


def test_consistency_withdrawal_is_honoured_too():
    included = _assess(consistency=_consistency())
    withdrawn = _assess(consistency=_consistency(
        excluded_from_risk=True,
        exclusion_reason="A face was visible in only 20% of sampled frames."))

    assert "av_consistency" in _keys(included["signals"])
    assert "av_consistency" not in _keys(withdrawn["signals"])
    entry = next(item for item in withdrawn["excluded"] if item["key"] == "av_consistency")
    assert "20%" in entry["reason"]


def test_a_module_without_the_flag_is_still_fused():
    """Absence of the key must not read as withdrawal — most modules never set it."""
    payload = _voice()
    del payload["excluded_from_risk"]

    assert "voice" in _keys(_assess(voice=payload)["signals"])


def test_an_unavailable_module_is_still_excluded_by_status():
    """The pre-existing gate has to keep working alongside the new one."""
    result = _assess(voice={"status": "unavailable", "voice_match_score": None,
                            "reason": "No audio track."})

    assert "voice" not in _keys(result["signals"])
    entry = next(item for item in result["excluded"] if item["key"] == "voice")
    assert entry["reason"] == "No audio track."


# ── the arithmetic still has to hold ─────────────────────────────────────────

def test_weights_renormalise_over_what_survived_the_gate():
    result = _assess(voice=_voice(), consistency=_consistency(excluded_from_risk=True))

    used = result["signals"]
    assert len(used) == 1
    assert used[0]["effective_weight"] == pytest.approx(1.0, abs=1e-4), (
        "a withdrawn module must not leave its weight in the denominator"
    )
    assert result["total_declared_weight_available"] == pytest.approx(WEIGHTS["voice"], abs=1e-4)


def test_withdrawal_neither_raises_nor_lowers_the_score():
    """A withdrawn module must behave exactly like an absent one."""
    withdrawn = _assess(voice=_voice(voice_match_score=0.9),
                        consistency=_consistency(excluded_from_risk=True))
    absent = _assess(voice=_voice(voice_match_score=0.9))

    assert withdrawn["overall_risk_score"] == absent["overall_risk_score"]


def test_every_reported_signal_carries_its_arithmetic():
    """An investigator has to be able to redo the sum by hand."""
    result = _assess(voice=_voice(), consistency=_consistency())

    total = 0.0
    for signal in result["signals"]:
        for field in ("raw_value", "normalized", "weight", "effective_weight", "contribution"):
            assert signal.get(field) is not None, f"{signal['key']} is missing {field}"
        assert signal["contribution"] == pytest.approx(
            signal["effective_weight"] * signal["normalized"], abs=1e-4)
        total += signal["contribution"]

    assert result["overall_risk_score"] == pytest.approx(total, abs=1e-4)
