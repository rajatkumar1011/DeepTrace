"""Evidence integrity re-verification.

The claim DeepTrace makes is narrow and must hold exactly: preserved files are
re-hashed from disk and compared to the digest recorded at preservation time, and
a mismatch is reported as a mismatch rather than quietly repaired.
"""

import os

from services.forensics import calculate_sha256
from services.integrity import (
    MISMATCH,
    MISSING,
    NO_RECORDED_HASH,
    VERIFIED,
    verify_artifact,
    verify_investigation,
)


def test_untouched_file_verifies(tmp_file):
    path = tmp_file("evidence.bin", b"original bytes")
    outcome = verify_artifact(path, calculate_sha256(path))

    assert outcome["status"] == VERIFIED
    assert outcome["current_sha256"] == outcome["recorded_sha256"]


def test_modified_file_is_reported_as_mismatch_not_repaired(tmp_file):
    path = tmp_file("evidence.bin", b"original bytes")
    recorded = calculate_sha256(path)

    with open(path, "wb") as handle:
        handle.write(b"tampered bytes")

    outcome = verify_artifact(path, recorded)
    assert outcome["status"] == MISMATCH
    assert outcome["recorded_sha256"] == recorded
    assert outcome["current_sha256"] != recorded
    # The recorded digest must survive verification unchanged: nothing is re-stamped.
    assert calculate_sha256(path) == outcome["current_sha256"]


def test_single_flipped_bit_is_detected(tmp_file):
    """A one-byte change must break the digest — no truncated comparison."""
    path = tmp_file("evidence.bin", b"A" * 4096)
    recorded = calculate_sha256(path)

    with open(path, "r+b") as handle:
        handle.seek(2048)
        handle.write(b"B")

    assert verify_artifact(path, recorded)["status"] == MISMATCH


def test_deleted_file_is_reported_missing(tmp_file):
    path = tmp_file("evidence.bin", b"bytes")
    recorded = calculate_sha256(path)
    os.remove(path)

    outcome = verify_artifact(path, recorded)
    assert outcome["status"] == MISSING
    assert outcome["current_sha256"] is None


def test_artifact_without_a_recorded_digest_is_not_claimed_verified(tmp_file):
    """Absence of a recorded hash must never be reported as a successful check."""
    path = tmp_file("evidence.bin", b"bytes")
    outcome = verify_artifact(path, None)

    assert outcome["status"] == NO_RECORDED_HASH
    assert outcome["status"] != VERIFIED
    assert outcome["current_sha256"] == calculate_sha256(path)
    assert "cannot be confirmed" in outcome["detail"]


def test_whole_case_is_intact_when_every_artifact_matches(tmp_file):
    items = []
    for index in range(3):
        path = tmp_file(f"artifact_{index}.bin", f"payload {index}".encode())
        items.append({"id": index, "evidence_type": "frame", "file_path": path,
                      "sha256_hash": calculate_sha256(path)})

    result = verify_investigation(items)
    assert result["chain_intact"] is True
    assert result["counts"][VERIFIED] == 3
    assert result["counts"][MISMATCH] == 0
    assert result["artifacts_checked"] == 3
    assert result["algorithm"] == "SHA-256"


def test_one_bad_artifact_fails_the_whole_case(tmp_file):
    good = tmp_file("good.bin", b"good")
    bad = tmp_file("bad.bin", b"good")
    recorded_bad = calculate_sha256(bad)
    with open(bad, "wb") as handle:
        handle.write(b"altered")

    result = verify_investigation([
        {"id": 1, "evidence_type": "original", "file_path": good, "sha256_hash": calculate_sha256(good)},
        {"id": 2, "evidence_type": "frame", "file_path": bad, "sha256_hash": recorded_bad},
    ])

    assert result["chain_intact"] is False
    assert result["counts"][MISMATCH] == 1
    assert "FAILED" in result["summary"]


def test_empty_case_does_not_claim_integrity():
    """Zero artifacts is not a passing integrity check."""
    result = verify_investigation([])
    assert result["chain_intact"] is False
    assert result["artifacts_checked"] == 0
    assert "No preserved artifacts" in result["summary"]


def test_verification_states_its_own_limits():
    """The admissibility caveat must travel with every result (see §27)."""
    result = verify_investigation([])
    limitations = result["limitations"].lower()
    assert "admissibility" in limitations
    assert "does not" in limitations
