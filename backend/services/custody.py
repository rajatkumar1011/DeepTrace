"""Chain-of-custody assembly and the hash-versus-analysis boundary.

A custody record answers one narrow question: for this case, what does DeepTrace
actually know about the handling of the evidence, and what does that knowledge
prove? Every value is read from rows the pipeline already wrote — the acquisition
digest, the derived artifacts, the recorded chronology, a live re-verification.
Nothing is inferred, and the gaps are reported as plainly as the facts.

The four claim lists below are the single source of truth for the integrity
boundary. The UI and the PDF report both quote them verbatim, so a claim can
never drift between the screen an affected person reads and the document an
investigating officer files.

Two constraints shaped the wording, and both come from the schema rather than
from caution:

* No table records an operator, custodian, user or session. DeepTrace is a
  single-operator local tool, so the record shows what happened to a file and
  never who did it. No statement here may imply an identified handler — which
  also means this is only ever *half* a chain of custody, and says so.
* ``timeline_events`` is an ordinary mutable table. Events are written in order
  and read back in order, which is worth stating, but nothing enforces
  append-only storage — so "immutable" is not an available word. Neither, on
  inspection, is "tamper-evident": the digest lives in the same writable local
  database as the file it describes, so altering both together verifies clean.
  What re-hashing genuinely catches is corruption and any change made to a file
  without a matching change to its record, and that is what the copy claims.
"""

from __future__ import annotations

HASH_ALGORITHM = "SHA-256"

#: What a full chain of custody requires, and which half DeepTrace can evidence.
#: Stated first, everywhere the custody record is shown, so a reader is never
#: left to assume the missing half was covered.
CUSTODY_SCOPE = {
    "definition": (
        "A complete chain of custody records four things about an item of evidence: what it is, "
        "who held it, when it passed from one holder to the next, and under what authority."
    ),
    "deeptrace_supplies": [
        "What the item is — the exact bytes received, identified by a digest computed as they "
        "were written to disk.",
        "What was produced from it — every frame, audio track and overlay the pipeline derived, "
        "each with its own digest.",
        "When each of those things was recorded, in sequence, by this machine's clock.",
        "Whether the preserved files still match the digests recorded for them.",
    ],
    "investigator_supplies": [
        "Who held the media before it was submitted to DeepTrace, and how they obtained it.",
        "Who operated DeepTrace, on what authority, and who has had access to this machine.",
        "Every hand-off of the exported report and evidence package after it leaves DeepTrace.",
        "Any external timestamping, sealing or notarisation the case requires.",
    ],
    "statement": (
        "DeepTrace evidences the file half of the chain and records no custodian, so this is a "
        "file-integrity record rather than a complete chain of custody. The investigating "
        "officer supplies the custodial half from their own case notes; the two together form "
        "the chain."
    ),
}

#: What a matching digest genuinely establishes.
HASHING_PROVES = [
    {
        "claim": "The stored file is byte-for-byte what DeepTrace received",
        "detail": "The digest is computed while the upload is being written to disk, over the "
                  "same byte stream that lands in the evidence store. It therefore belongs to "
                  "the bytes DeepTrace actually holds — not to a second, separate read, and "
                  "not to any value the uploader supplied. Client-submitted hashes are never "
                  "accepted.",
    },
    {
        "claim": "Change to a preserved file is detectable, as long as the record is untouched",
        "detail": "Re-reading a file and re-hashing it reproduces the recorded digest exactly if "
                  "nothing changed, and altering a single bit produces an entirely different "
                  "digest. This reliably catches storage corruption, truncated or failed "
                  "transfers, re-encoding, re-saving through an editor, accidental overwriting, "
                  "and modification by anyone who can reach the evidence file but not this "
                  "database. It does not catch someone who changes both.",
    },
    {
        "claim": "Two files are, or are not, the same file",
        "detail": "Identical digests mean identical bytes. This is what links the media you "
                  "submitted to the copy described in the report, and to any traced copy that "
                  "turns out to be the same file rather than merely a similar one.",
    },
    {
        "claim": "Which exact file each finding refers to",
        "detail": "Every analysis result is attached to a case whose original file has a "
                  "recorded digest, so a finding cannot later be re-pointed at a different "
                  "file without the mismatch showing.",
    },
]

#: What a matching digest is routinely assumed to establish, and does not.
HASHING_DOES_NOT_PROVE = [
    {
        "claim": "Not who created, uploaded or handled the file",
        "detail": "DeepTrace records no operator, custodian or account identity. It runs as a "
                  "single-operator local tool, so the custody record describes what happened "
                  "to the file, never who did it.",
    },
    {
        "claim": "Not when the content was originally made",
        "detail": "The recorded time is when DeepTrace received the file, taken from this "
                  "machine's clock. There is no third-party timestamp authority "
                  "countersignature (RFC 3161), so the time is a local assertion.",
    },
    {
        "claim": "Not whether the content is authentic or manipulated",
        "detail": "A hash is indifferent to what a file depicts. A fabricated video hashes "
                  "just as cleanly as a genuine one. Integrity and authenticity are separate "
                  "questions, and only the first is settled by hashing.",
    },
    {
        "claim": "Not tamper-proof, and not fully tamper-evident either",
        "detail": "SHA-256 is a detection primitive, not a protection primitive. The digest is "
                  "stored in the same local database that the same person can edit, and it is "
                  "not signed, hash-chained, or held anywhere independent of the file it "
                  "describes. Changing a preserved file alone is detected; changing the file "
                  "and its recorded digest together is not. Verification is therefore a "
                  "consistency check between two artifacts under common control, not a "
                  "guarantee against a determined local operator.",
    },
    {
        "claim": "Nothing about the file before DeepTrace received it",
        "detail": "The digest begins at the moment the bytes entered DeepTrace's write loop. It "
                  "says nothing about whether the media was edited, re-encoded or re-uploaded "
                  "before it was submitted, or about where it had been until then.",
    },
    {
        "claim": "Not legal admissibility",
        "detail": "Admissibility is decided by a court under the applicable rules of evidence, "
                  "on the record before it. A checksum supports an integrity argument; it does "
                  "not by itself make evidence admissible.",
    },
]

#: What the model outputs support.
AI_ESTABLISHES = [
    {
        "claim": "A probability of manipulation, not a verdict",
        "detail": "The manipulation model (DeepfakeBench Xception) returns a score for each "
                  "sampled frame. The case score is a weighted fusion of only the signals that "
                  "actually ran, and it is an investigative prioritisation aid.",
    },
    {
        "claim": "Similarity to an enrolled reference, not identity",
        "detail": "Face comparison (FaceNet) and speaker comparison (ECAPA-TDNN) produce "
                  "distances between embeddings. A high similarity means the media is "
                  "consistent with the enrolled reference — it does not assert that the person "
                  "is the same person.",
    },
    {
        "claim": "Indicators measured over a sample",
        "detail": "Video is analysed on sampled frames rather than every frame, and audio on "
                  "the extracted track. Findings describe what was examined, and the report "
                  "states how much that was.",
    },
    {
        "claim": "Results that are reproducible, and deliberately not preserved",
        "detail": "Analysis output is derived data: it can be discarded and recomputed from the "
                  "preserved original at any time. Preserved evidence cannot be recomputed, "
                  "which is why the two are stored separately and only one of them is hashed "
                  "as a matter of record.",
    },
]

#: What the model outputs are routinely assumed to support, and do not.
AI_DOES_NOT_ESTABLISH = [
    {
        "claim": "Not who made the media, or with which tool",
        "detail": "No module attributes content to a creator, an account, a device or a "
                  "generation tool. DeepTrace does not identify whoever produced a file.",
    },
    {
        "claim": "Not intent, and not a criminal offence",
        "detail": "A score describes signal in a file. Whether an act was unlawful, and what "
                  "was intended by it, is for an investigator and a court to determine.",
    },
    {
        "claim": "Not a guarantee in either direction",
        "detail": "These models have measured error rates. A low score does not rule out "
                  "manipulation, and a high score is not proof of it. Compression, "
                  "re-uploading and screen recording all degrade the signal the models rely on.",
    },
    {
        "claim": "Not authority over the preserved evidence",
        "detail": "Analysis never modifies a preserved file or its recorded digest. Re-running "
                  "the pipeline can change the findings; it cannot change the evidence.",
    },
]

#: Role of each preserved artifact type in the chain, by the stage that writes it.
_DERIVATION = {
    "original": (
        "acquired",
        "Root of the chain — acquired",
        "Received from the submitter and written to the evidence store, hashed during the "
        "write. Never overwritten or replaced.",
    ),
    "traced_copy": (
        "acquired",
        "Separately acquired copy",
        "Retrieved from a source supplied by the operator, then hashed on arrival. Its digest "
        "is compared against the original to establish whether it is the same file.",
    ),
    "frame": (
        "derived",
        "Derived from the original",
        "Sampled from the original media by the frame-extraction stage, then hashed and "
        "preserved so the exact image each frame-level finding refers to is recoverable.",
    ),
    "audio": (
        "derived",
        "Derived from the original",
        "Demuxed from the original media by the audio-extraction stage, then hashed and "
        "preserved as the input the audio and speaker modules actually examined.",
    ),
    "localization": (
        "derived",
        "Derived visualisation",
        "Rendered from a sampled frame by the localization stage. It is an explainable "
        "image-forensics overlay, not a trained segmentation mask, and not an assertion that "
        "the highlighted region was edited.",
    ),
}

_DERIVATION_NOTE = (
    "Lineage is recorded by the pipeline stage that produced each artifact. DeepTrace does not "
    "store an explicit parent reference on individual files, so the relationships below reflect "
    "how each stage operates rather than a per-file pointer."
)


def _artifact_role(evidence_type: str | None) -> tuple[str, str, str]:
    return _DERIVATION.get(
        evidence_type or "",
        ("derived", "Derived artifact", "Produced by the analysis pipeline from the "
                                       "preserved original media."),
    )


def _stamp(value) -> str | None:
    return str(value) if value else None


def build_custody_record(inv, integrity: dict, identity=None) -> dict:
    """Assemble the custody record for one investigation.

    ``inv`` is an ``Investigation`` row; its ``evidence_items`` and
    ``timeline_events`` collections supply the chain. ``integrity`` is the output
    of :func:`services.integrity.verify_investigation`, reused rather than
    recomputed so the screen and the report cannot disagree about the same check.
    """
    artifacts = sorted(inv.evidence_items, key=lambda item: (str(item.created_at or ""), item.id))
    events = sorted(inv.timeline_events, key=lambda event: (str(event.created_at or ""), event.id))

    acquisition = {
        "case_reference": f"DT-{inv.id:06d}",
        "submitted_filename": inv.filename,
        "media_type": inv.media_type,
        "file_size_bytes": inv.file_size_bytes,
        "received_at": _stamp(inv.created_at),
        "algorithm": HASH_ALGORITHM,
        "sha256": inv.sha256_hash,
        "perceptual_hash": inv.perceptual_hash,
        "hash_binding": (
            "Computed server-side while the upload was written to disk, in the same single pass "
            "as the write, over the same byte stream that was persisted. The recorded byte count "
            "was accumulated in that same pass. A hash supplied by the client is never accepted "
            "or recorded, and neither is the client's declared content type."
        ),
        "derived_hash_binding": (
            "Artifacts the pipeline produces — sampled frames, the extracted audio track, "
            "localization overlays — are hashed by re-reading each file after it is written, "
            "rather than during the write. The distinction matters only for the original, whose "
            "digest is bound to the acquisition itself."
        ),
        "type_determination": (
            "Media type was determined from the sanitised filename extension checked against a "
            "fixed allowlist, not from the file's content. The recorded type is a label, not a "
            "verified format identification."
        ),
        "filename_note": (
            "The stored filename is a sanitised derivative of the submitted name: the path is "
            "reduced to a bare basename and unsafe characters are replaced, so it may differ "
            "from what the submitter's device called the file."
        ),
        "clock_source": (
            "Timestamps come from the clock of the machine running DeepTrace. No third-party "
            "timestamp authority countersigns them."
        ),
    }

    ledger = []
    for item in artifacts:
        origin, role_label, role_detail = _artifact_role(item.evidence_type)
        ledger.append({
            "evidence_id": item.id,
            "evidence_type": item.evidence_type,
            "origin": origin,
            "role": role_label,
            "role_detail": role_detail,
            "preserved_at": _stamp(item.created_at),
            "timestamp_offset": item.timestamp_offset,
            "sha256": item.sha256_hash,
            "digest_recorded": bool(item.sha256_hash),
        })

    chronology = [
        {
            "sequence": index + 1,
            "event_type": event.event_type,
            "description": event.description,
            "recorded_at": _stamp(event.created_at),
        }
        for index, event in enumerate(events)
    ]

    acquired = [entry for entry in ledger if entry["origin"] == "acquired"]
    derived = [entry for entry in ledger if entry["origin"] == "derived"]
    undigested = [entry for entry in ledger if not entry["digest_recorded"]]

    return {
        "investigation_id": inv.id,
        "custody_scope": CUSTODY_SCOPE,
        "acquisition": acquisition,
        "derivation_note": _DERIVATION_NOTE,
        "artifact_ledger": ledger,
        "counts": {
            "artifacts": len(ledger),
            "acquired": len(acquired),
            "derived": len(derived),
            "without_digest": len(undigested),
        },
        "chronology": chronology,
        "chronology_note": (
            "Case events are written as they happen and read back in the order they were "
            "written. The table is ordinary storage, so this is a record kept in sequence — not "
            "an append-only or cryptographically chained log. Each event is committed on its "
            "own, so a stage that records an action and then fails can leave a claim standing "
            "that nothing later contradicts. Running an integrity re-verification also appends "
            "an event, which is why simply viewing this custody record does not."
        ),
        "integrity_check": {
            "verified_at": integrity.get("verified_at"),
            "algorithm": integrity.get("algorithm"),
            "artifacts_checked": integrity.get("artifacts_checked"),
            "chain_intact": integrity.get("chain_intact"),
            "summary": integrity.get("summary"),
            "counts": integrity.get("counts"),
            "method": integrity.get("method"),
            "limitations": integrity.get("limitations"),
        },
        "hashing_proves": HASHING_PROVES,
        "hashing_does_not_prove": HASHING_DOES_NOT_PROVE,
        "ai_establishes": AI_ESTABLISHES,
        "ai_does_not_establish": AI_DOES_NOT_ESTABLISH,
        "custody_gaps": _custody_gaps(inv, undigested, identity),
        "boundary_summary": (
            f"{HASH_ALGORITHM} hashing establishes that the preserved files have not changed "
            "since DeepTrace received them. The AI analysis estimates how likely the content "
            "is manipulated, and how closely it resembles an enrolled reference. Neither "
            "answers the other's question, and the report keeps them in separate sections for "
            "that reason."
        ),
    }


def _custody_gaps(inv, undigested: list[dict], identity) -> list[dict]:
    """Limitations of this specific record, derived from what is actually stored."""
    gaps = [
        {
            "gap": "No identified custodian",
            "detail": "No table in DeepTrace records an operator, account or session, and there "
                      "is no authentication layer that could establish one. The chain covers "
                      "the handling of files, not the people who handled them, and there is no "
                      "hand-off, access or export log. An investigator relying on this record "
                      "supplies the custodial half from their own case notes.",
        },
        {
            "gap": "No third-party timestamping",
            "detail": "Times are taken from the local system clock. There is no RFC 3161 "
                      "timestamp authority, cryptographic signature, notarisation or external "
                      "witness, so the chronology is entirely self-recorded.",
        },
        {
            "gap": "Verification cannot detect a change made to both file and record",
            "detail": "The recorded digest sits in the same writable local database as the file "
                      "it describes, and is not signed or chained. Altering a preserved file is "
                      "detected; altering the file and its stored digest together verifies "
                      "clean. This has been confirmed against a copy of the store rather than "
                      "assumed, and it bounds what any 'verified' result here can mean.",
        },
        {
            "gap": "Evidence files are served without authentication",
            "detail": "Preserved originals and derived frames are exposed by the local server "
                      "as static files, with no credential required and no read-only or "
                      "write-once protection applied after hashing. DeepTrace is intended to "
                      "run on a single trusted machine, and offers no protection if it does not.",
        },
        {
            "gap": "Single local store",
            "detail": "The custody record lives in this machine's database and evidence folder. "
                      "There is no off-machine replica and no write-once medium, so it inherits "
                      "the durability of the host it runs on.",
        },
    ]

    if identity is not None:
        gaps.append({
            "gap": "Reference media is stored but not hashed",
            "detail": "The enrolled reference image and voice sample for the protected "
                      "identity are retained with a recorded consent decision, but DeepTrace "
                      "does not compute a digest for them. Integrity claims in this record "
                      "cover the submitted media and its derived artifacts only.",
        })

    if undigested:
        ids = ", ".join(str(entry["evidence_id"]) for entry in undigested[:12])
        more = "" if len(undigested) <= 12 else f" (first 12 of {len(undigested)} shown)"
        gaps.append({
            "gap": f"{len(undigested)} preserved artifact(s) have no recorded digest",
            "detail": f"Evidence IDs {ids}{more} cannot be re-verified, because no hash was "
                      "recorded when they were preserved. They remain in the register, marked "
                      "as unverifiable rather than as verified.",
        })

    if inv.analysis_completed_at is None:
        gaps.append({
            "gap": "Analysis has not completed for this case",
            "detail": "The custody record covers what has been preserved so far. Derived "
                      "artifacts from stages that have not run yet are absent from the ledger.",
        })

    return gaps
