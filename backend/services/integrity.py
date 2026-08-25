"""Evidence integrity re-verification.

Recording a hash at intake only proves what the bytes were *then*. This module
answers the question a court or a reviewer actually asks: do the preserved files
on disk still match the digests recorded when they were preserved?

Every artifact is re-hashed from disk and compared to its stored value. Nothing
is repaired or re-recorded — a mismatch is reported as a mismatch.
"""

import os
from datetime import datetime, timezone

from services.forensics import calculate_sha256

VERIFIED = "verified"
MISMATCH = "mismatch"
MISSING = "missing"
NO_RECORDED_HASH = "no_recorded_hash"

_LABELS = {
    "original": "Original submitted media",
    "frame": "Sampled video frame",
    "localization": "Manipulation localization overlay",
    "audio": "Extracted audio track",
    "traced_copy": "Retrieved external copy",
    "report": "Generated forensic report",
}


def describe(evidence_type: str | None) -> str:
    return _LABELS.get(evidence_type or "", (evidence_type or "artifact").replace("_", " ").capitalize())


def verify_artifact(file_path: str | None, recorded_hash: str | None) -> dict:
    """Re-hash one artifact and compare against the recorded digest."""
    if not file_path or not os.path.isfile(file_path):
        return {
            "status": MISSING,
            "recorded_sha256": recorded_hash,
            "current_sha256": None,
            "detail": "The preserved file is no longer present at its recorded location.",
        }
    current = calculate_sha256(file_path)
    if current is None:
        return {
            "status": MISSING,
            "recorded_sha256": recorded_hash,
            "current_sha256": None,
            "detail": "The file exists but could not be read for hashing.",
        }
    if not recorded_hash:
        return {
            "status": NO_RECORDED_HASH,
            "recorded_sha256": None,
            "current_sha256": current,
            "detail": (
                "No SHA-256 was recorded for this artifact when it was preserved, so integrity "
                "cannot be confirmed. The digest computed now is shown for reference."
            ),
        }
    if current == recorded_hash:
        return {
            "status": VERIFIED,
            "recorded_sha256": recorded_hash,
            "current_sha256": current,
            "detail": "The file on disk still hashes to its recorded SHA-256.",
        }
    return {
        "status": MISMATCH,
        "recorded_sha256": recorded_hash,
        "current_sha256": current,
        "detail": (
            "The file on disk does NOT match its recorded SHA-256. The artifact has been altered, "
            "replaced or corrupted since it was preserved."
        ),
    }


def verify_investigation(items: list[dict]) -> dict:
    """Re-verify a whole case.

    ``items`` are dicts with ``id``, ``evidence_type``, ``file_path``,
    ``sha256_hash`` and optional ``public_path``/``timestamp_offset``.
    """
    checked: list[dict] = []
    for item in items:
        outcome = verify_artifact(item.get("file_path"), item.get("sha256_hash"))
        checked.append({
            "evidence_id": item.get("id"),
            "evidence_type": item.get("evidence_type"),
            "label": describe(item.get("evidence_type")),
            "public_path": item.get("public_path"),
            "timestamp_offset": item.get("timestamp_offset"),
            "preserved_at": item.get("created_at"),
            **outcome,
        })

    counts = {
        VERIFIED: sum(1 for c in checked if c["status"] == VERIFIED),
        MISMATCH: sum(1 for c in checked if c["status"] == MISMATCH),
        MISSING: sum(1 for c in checked if c["status"] == MISSING),
        NO_RECORDED_HASH: sum(1 for c in checked if c["status"] == NO_RECORDED_HASH),
    }
    total = len(checked)
    intact = total > 0 and counts[MISMATCH] == 0 and counts[MISSING] == 0

    if total == 0:
        summary = "No preserved artifacts were recorded for this investigation."
    elif intact and counts[NO_RECORDED_HASH] == 0:
        summary = (
            f"All {total} preserved artifact(s) re-hash to their recorded SHA-256 values. "
            "The evidence set is intact."
        )
    elif intact:
        summary = (
            f"{counts[VERIFIED]} of {total} artifact(s) re-hash to their recorded values; "
            f"{counts[NO_RECORDED_HASH]} had no digest recorded at preservation time. "
            "No mismatches or missing files were found."
        )
    else:
        problems = []
        if counts[MISMATCH]:
            problems.append(f"{counts[MISMATCH]} hash mismatch(es)")
        if counts[MISSING]:
            problems.append(f"{counts[MISSING]} missing file(s)")
        summary = (
            f"Integrity check FAILED: {' and '.join(problems)} out of {total} artifact(s). "
            "The affected artifacts can no longer be relied on."
        )

    return {
        "verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "algorithm": "SHA-256",
        "artifacts_checked": total,
        "counts": counts,
        "chain_intact": intact,
        "summary": summary,
        "artifacts": checked,
        "method": "Each preserved file is re-read from disk and re-hashed, then compared byte-for-byte "
                  "against the digest recorded at preservation time.",
        "limitations": (
            "This verifies internal consistency of the local evidence store. It does not provide "
            "third-party timestamping, notarisation or tamper-proof custody, and does not by itself "
            "establish legal admissibility."
        ),
    }
