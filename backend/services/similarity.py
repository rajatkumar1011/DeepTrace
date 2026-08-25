"""Copy tracing across the local evidence store.

Answers one question: does this media — or a visually near-identical version of
it — already appear in another case in this DeepTrace instance?

Scope is stated on every result: this searches the local evidence index only. It
is not an internet-wide search, and absence of a match means nothing beyond "not
in this database".

The previous implementation compared every evidence row against every other row
and emitted one match per pair, which produced hundreds of duplicate rows for a
single repeated file. Matches are now reduced to the single best hit per related
investigation.
"""

from services.forensics import phash_similarity, similarity_label

EXACT = "exact_duplicate"
NEAR = "near_duplicate"
SIMILAR = "similar_content"

NEAR_THRESHOLD = 0.95
SIMILAR_THRESHOLD = 0.80
MAX_RELATED_CASES = 25
MAX_INDEX_ROWS = 20000


def _match_type(similarity: float, exact: bool) -> str | None:
    if exact:
        return EXACT
    if similarity >= NEAR_THRESHOLD:
        return NEAR
    if similarity >= SIMILAR_THRESHOLD:
        return SIMILAR
    return None


def _rank(match_type: str) -> int:
    return {EXACT: 3, NEAR: 2, SIMILAR: 1}.get(match_type, 0)


def find_local_copies(current_items: list[dict], index_items: list[dict],
                      case_titles: dict[int, str] | None = None) -> dict:
    """Best match per related investigation.

    ``current_items``/``index_items`` are dicts with keys: ``evidence_id``,
    ``investigation_id``, ``evidence_type``, ``sha256``, ``perceptual_hash``,
    ``timestamp_offset``.
    """
    case_titles = case_titles or {}
    indexed_case_ids = {item["investigation_id"] for item in index_items}
    best: dict[int, dict] = {}

    for mine in current_items:
        my_sha = mine.get("sha256")
        my_phash = mine.get("perceptual_hash")
        if not my_sha and not my_phash:
            continue

        for theirs in index_items:
            exact = bool(my_sha and theirs.get("sha256") and my_sha == theirs["sha256"])
            similarity = 1.0 if exact else phash_similarity(my_phash, theirs.get("perceptual_hash"))
            match_type = _match_type(similarity, exact)
            if not match_type:
                continue

            case_id = theirs["investigation_id"]
            # Keep the strongest evidence of a relationship per case: an exact byte
            # match outranks a perceptual near-match even when the latter scores 1.0
            # on the coarser 64-bit hash.
            candidate = {
                "matched_investigation_id": case_id,
                "matched_investigation_filename": case_titles.get(case_id),
                "match_type": match_type,
                "similarity": round(float(similarity), 4),
                "similarity_label": "Byte-identical" if exact else similarity_label(similarity),
                "basis": (
                    "SHA-256 digests are identical."
                    if exact else
                    f"Perceptual hash agreement {similarity * 100:.1f}%."
                ),
                "this_case_evidence_id": mine.get("evidence_id"),
                "this_case_evidence_type": mine.get("evidence_type"),
                "this_case_timestamp_offset": mine.get("timestamp_offset"),
                "matched_evidence_id": theirs.get("evidence_id"),
                "matched_evidence_type": theirs.get("evidence_type"),
                "matched_timestamp_offset": theirs.get("timestamp_offset"),
            }
            existing = best.get(case_id)
            if existing is None or (_rank(match_type), similarity) > (
                _rank(existing["match_type"]), existing["similarity"]
            ):
                best[case_id] = candidate

    matches = sorted(
        best.values(),
        key=lambda m: (_rank(m["match_type"]), m["similarity"]),
        reverse=True,
    )
    truncated = max(0, len(matches) - MAX_RELATED_CASES)
    matches = matches[:MAX_RELATED_CASES]

    exact_count = sum(1 for m in matches if m["match_type"] == EXACT)
    near_count = sum(1 for m in matches if m["match_type"] == NEAR)
    similar_count = sum(1 for m in matches if m["match_type"] == SIMILAR)
    best_similarity = matches[0]["similarity"] if matches else 0.0

    if not matches:
        summary = (
            f"No matching or visually similar media was found among the "
            f"{len(indexed_case_ids)} other case(s) in this instance's evidence index."
        )
    else:
        parts = []
        if exact_count:
            parts.append(f"{exact_count} case(s) hold a byte-identical copy")
        if near_count:
            parts.append(f"{near_count} case(s) hold a near-identical version")
        if similar_count:
            parts.append(f"{similar_count} case(s) hold visually similar content")
        summary = (
            "This media also appears elsewhere in the local evidence index: "
            + "; ".join(parts) + "."
        )

    return {
        "status": "completed",
        "method": "SHA-256 exact match + 64-bit perceptual hash (Hamming distance)",
        "model_status": "Deterministic hash comparison (no ML model involved)",
        "scope": (
            "Local evidence index only — the media preserved by this DeepTrace instance. "
            "This is not an internet-wide or platform-wide search."
        ),
        "cases_indexed": len(indexed_case_ids),
        "evidence_rows_compared": len(index_items),
        "items_compared_from_this_case": len(current_items),
        "match_count": len(matches),
        "exact_duplicate_cases": exact_count,
        "near_duplicate_cases": near_count,
        "similar_content_cases": similar_count,
        "best_similarity": round(float(best_similarity), 4),
        "best_similarity_label": matches[0]["similarity_label"] if matches else "No match",
        "matches": matches,
        "truncated_matches": truncated,
        "thresholds": {
            "near_duplicate": NEAR_THRESHOLD,
            "similar_content": SIMILAR_THRESHOLD,
        },
        "summary": summary,
        "interpretation": (
            "A match indicates the same or near-identical media is present in another case in "
            "this instance, which is evidence of redistribution. It is not evidence of "
            "manipulation, and no match does not mean the media has not been shared elsewhere."
        ),
    }
