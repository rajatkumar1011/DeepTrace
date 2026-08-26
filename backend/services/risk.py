"""Explainable identity + manipulation risk fusion.

Design constraints that shaped this module:

* Every contributing signal exposes its raw value, the threshold it was measured
  against, its weight, its direction, and its arithmetic contribution. An
  investigator must be able to reconstruct the number by hand.
* Unavailable signals are *excluded and named*, never silently defaulted to zero.
  A missing voice sample must not read as "voice mismatch".
* Absence of provenance credentials is not treated as evidence of anything. Most
  legitimate media carries no Content Credentials.
* The output is an analytical prioritisation aid. It is never described as proof,
  and the disclaimer travels with the payload into the API and the PDF.
"""

# Same-person decision thresholds published for the underlying models.
FACE_THRESHOLD = 0.60          # cosine similarity, InceptionResnetV1 / VGGFace2
VOICE_THRESHOLD = 0.25         # cosine similarity, ECAPA-TDNN / VoxCeleb
MANIPULATION_THRESHOLD = 0.50  # softmax P(fake), DeepfakeBench Xception

WEIGHTS = {
    "manipulation": 0.35,
    "identity": 0.25,
    "voice": 0.12,
    "av_consistency": 0.10,
    "provenance": 0.08,
    "audio_editing": 0.05,
    "propagation": 0.05,
}

RISK_BANDS = [(0.75, "CRITICAL"), (0.50, "HIGH"), (0.25, "MEDIUM"), (0.0, "LOW")]


def _band(score: float) -> str:
    for floor, label in RISK_BANDS:
        if score >= floor:
            return label
    return "LOW"


def _level(score: float) -> str:
    if score >= 0.75:
        return "HIGH"
    if score >= 0.5:
        return "MEDIUM"
    if score >= 0.25:
        return "LOW"
    return "MINIMAL"


def _threshold_normalise(value: float, threshold: float) -> float:
    """Map a similarity onto [0, 1] with the model's decision threshold at 0.5.

    A raw cosine similarity is not a probability, so feeding it straight into a
    weighted average would treat 0.4 (a clear non-match) as meaningful risk. This
    anchors the midpoint at the published threshold instead.
    """
    if value >= threshold:
        headroom = max(1e-6, 1.0 - threshold)
        return min(1.0, 0.5 + 0.5 * (value - threshold) / headroom)
    return max(0.0, 0.5 * (value / threshold)) if threshold > 0 else 0.0


def _seconds_label(seconds) -> str:
    if seconds is None:
        return "n/a"
    minutes, secs = divmod(float(seconds), 60)
    return f"{int(minutes):02d}:{secs:05.2f}"


def _fusable(module: dict | None, score_key: str) -> bool:
    """Whether a module's score may be given a weight.

    Three conditions, and the third is the one that matters. A module that
    completed and produced a number may still have established that its own
    measurement does not apply to this media — a speaker score from a
    half-second clip, an alignment figure from B-roll. It says so by setting
    ``excluded_from_risk``, and that judgement belongs to the module that made
    the measurement, not to the fusion that consumes it. Honouring the flag here
    is what makes it a contract rather than a comment: without this check the
    flag was set in three places and read in none.
    """
    if not module or module.get("status") != "completed":
        return False
    if module.get(score_key) is None:
        return False
    return not module.get("excluded_from_risk")


def _exclusion_reason(module: dict | None, default: str, fallback_key: str = "reason") -> str:
    """Why a module contributed nothing, preferring the module's own words."""
    module = module or {}
    return (module.get("exclusion_reason")
            or module.get("reason")
            or module.get(fallback_key)
            or default)


def fuse(*, deepfake: dict | None = None, identity: dict | None = None,
         voice: dict | None = None, consistency: dict | None = None,
         audio: dict | None = None, propagation: dict | None = None,
         provenance: dict | None = None, localization: dict | None = None,
         media_type: str = "video", identity_name: str | None = None) -> dict:
    """Combine module payloads into a weighted, fully itemised risk assessment."""
    signals: list[dict] = []
    excluded: list[dict] = []

    # ── Manipulation evidence ────────────────────────────────────────────────
    if deepfake and deepfake.get("manipulation_signal") is not None:
        value = float(deepfake["manipulation_signal"])
        frames = deepfake.get("frames_analyzed")
        suspicious = deepfake.get("suspicious_frame_count")
        detail = f"{deepfake.get('model_name', 'manipulation detector')} scored {value:.3f}"
        if frames:
            detail += f" as the mean over {frames} sampled frame(s)"
            if suspicious is not None:
                detail += f", {suspicious} of which exceeded the {MANIPULATION_THRESHOLD:.2f} threshold"
        detail += "."
        signals.append({
            "key": "manipulation",
            "label": "Manipulation evidence",
            "raw_value": round(value, 6),
            "raw_units": "P(manipulated) from softmax output",
            "threshold": MANIPULATION_THRESHOLD,
            "normalized": round(value, 6),
            "normalization": "Used directly — the model already outputs a probability in [0, 1].",
            "direction": "Higher increases risk",
            "weight": WEIGHTS["manipulation"],
            "level": _level(value),
            "detail": detail,
            "source_model": deepfake.get("model_name"),
        })
    else:
        excluded.append({
            "key": "manipulation",
            "label": "Manipulation evidence",
            "reason": (deepfake or {}).get("reason")
                      or "The manipulation detector produced no score for this media.",
        })

    # ── Identity match ───────────────────────────────────────────────────────
    if identity and identity.get("best_similarity") is not None:
        value = float(identity["best_similarity"])
        normalized = _threshold_normalise(value, FACE_THRESHOLD)
        subject = identity.get("reference_identity") or identity_name or "the enrolled identity"
        if value >= FACE_THRESHOLD:
            detail = (
                f"Best face similarity to {subject} is {value:.3f}, above the {FACE_THRESHOLD:.2f} "
                "same-person threshold, so the media does appear to depict the protected identity."
            )
        else:
            detail = (
                f"Best face similarity to {subject} is {value:.3f}, below the {FACE_THRESHOLD:.2f} "
                "same-person threshold, which weakens the case that this media depicts the "
                "protected identity."
            )
        signals.append({
            "key": "identity",
            "label": "Identity match",
            "raw_value": round(value, 6),
            "raw_units": "cosine similarity of face embeddings",
            "threshold": FACE_THRESHOLD,
            "normalized": round(normalized, 6),
            "normalization": f"Threshold-anchored: {FACE_THRESHOLD:.2f} cosine maps to 0.50.",
            "direction": "Higher increases risk (media more likely depicts the protected identity)",
            "weight": WEIGHTS["identity"],
            "level": _level(normalized),
            "detail": detail,
            "source_model": identity.get("model_name"),
        })
    else:
        excluded.append({
            "key": "identity",
            "label": "Identity match",
            "reason": (identity or {}).get("reason")
                      or "No enrolled identity was compared against this media.",
        })

    # ── Voice match ──────────────────────────────────────────────────────────
    if _fusable(voice, "voice_match_score"):
        value = float(voice["voice_match_score"])
        normalized = _threshold_normalise(max(0.0, value), VOICE_THRESHOLD)
        signals.append({
            "key": "voice",
            "label": "Voice match",
            "raw_value": round(value, 6),
            "raw_units": "cosine similarity of speaker embeddings",
            "threshold": VOICE_THRESHOLD,
            "normalized": round(normalized, 6),
            "normalization": f"Threshold-anchored: {VOICE_THRESHOLD:.2f} cosine maps to 0.50.",
            "direction": "Higher increases risk (voice more likely matches the protected identity)",
            "weight": WEIGHTS["voice"],
            "level": _level(normalized),
            "detail": voice.get("interpretation") or f"Speaker similarity {value:.3f}.",
            "source_model": voice.get("model_name"),
        })
    else:
        excluded.append({
            "key": "voice",
            "label": "Voice match",
            "reason": _exclusion_reason(voice, "Speaker comparison was not performed."),
        })

    # ── A/V consistency ──────────────────────────────────────────────────────
    if _fusable(consistency, "consistency_score"):
        alignment = float(consistency["consistency_score"])
        normalized = 1.0 - alignment
        duration = consistency.get("duration_agreement") or {}
        detail = (
            f"Face presence and audio activity agreed at {alignment * 100:.0f}% of sampled "
            "timestamps."
        )
        if duration.get("mismatch"):
            detail += f" {duration.get('observation')}"
        signals.append({
            "key": "av_consistency",
            "label": "Audio/video consistency",
            "raw_value": round(alignment, 6),
            "raw_units": "share of sampled timestamps where face presence and audio activity agree",
            "threshold": None,
            "normalized": round(normalized, 6),
            "normalization": "Inverted — low alignment increases risk.",
            "direction": "Lower alignment increases risk",
            "weight": WEIGHTS["av_consistency"],
            "level": _level(normalized),
            "detail": detail,
            "source_model": "OpenCV Haar cascade + PCM RMS windows",
        })
    else:
        excluded.append({
            "key": "av_consistency",
            "label": "Audio/video consistency",
            "reason": _exclusion_reason(
                consistency, "Audio/video alignment could not be measured.", fallback_key="details"),
        })

    # ── Provenance ───────────────────────────────────────────────────────────
    # Only *present* credentials move the score, and they move it down. Absence
    # is the norm for ordinary media and is deliberately not penalised.
    if provenance and provenance.get("credentials_found"):
        signals.append({
            "key": "provenance",
            "label": "Content Credentials (C2PA)",
            "raw_value": 1.0,
            "raw_units": "C2PA manifest present",
            "threshold": None,
            "normalized": 0.0,
            "normalization": "Verifiable credentials present — treated as risk-reducing.",
            "direction": "Presence of valid credentials reduces risk",
            "weight": WEIGHTS["provenance"],
            "level": "MINIMAL",
            "detail": (
                "A C2PA manifest is attached"
                + (f", generated by {provenance.get('claim_generator')}" if provenance.get("claim_generator") else "")
                + ". Credentials describe provenance; they do not by themselves prove the content "
                  "is unmanipulated."
            ),
            "source_model": "c2pa-python",
        })
    else:
        excluded.append({
            "key": "provenance",
            "label": "Content Credentials (C2PA)",
            "reason": (
                "No Content Credentials are attached. This is normal for most media and is NOT "
                "treated as evidence of manipulation, so provenance was excluded from the score."
            ),
        })

    # ── Audio editing indicators ─────────────────────────────────────────────
    if audio and audio.get("status") == "completed" and audio.get("editing_indicator") is not None:
        value = float(audio["editing_indicator"])
        count = audio.get("discontinuity_count", 0)
        signals.append({
            "key": "audio_editing",
            "label": "Audio editing indicators",
            "raw_value": round(value, 6),
            "raw_units": "composite of abrupt loudness transitions and clipping",
            "threshold": None,
            "normalized": round(value, 6),
            "normalization": "Composite indicator already bounded to [0, 1].",
            "direction": "Higher increases risk",
            "weight": WEIGHTS["audio_editing"],
            "level": _level(value),
            "detail": (
                f"{count} abrupt loudness transition(s) and a clipping ratio of "
                f"{(audio.get('levels') or {}).get('clipping_ratio', 0):.4f}. These indicate "
                "editing or re-encoding, not synthetic speech."
            ),
            "source_model": "Deterministic PCM signal analysis",
        })
    else:
        excluded.append({
            "key": "audio_editing",
            "label": "Audio editing indicators",
            "reason": (audio or {}).get("reason") or "No decoded audio track was analysed.",
        })

    # ── Propagation / redistribution ─────────────────────────────────────────
    if propagation and propagation.get("status") == "completed":
        value = float(propagation.get("best_similarity") or 0.0)
        matches = propagation.get("match_count") or 0
        if matches:
            signals.append({
                "key": "propagation",
                "label": "Redistribution in local index",
                "raw_value": round(value, 6),
                "raw_units": "best hash similarity to media held in other cases",
                "threshold": propagation.get("thresholds", {}).get("similar_content"),
                "normalized": round(value, 6),
                "normalization": "Best similarity used directly.",
                "direction": "Higher increases risk (media is circulating in more than one case)",
                "weight": WEIGHTS["propagation"],
                "level": _level(value),
                "detail": propagation.get("summary") or f"{matches} related case(s) found.",
                "source_model": "SHA-256 + perceptual hash",
            })
        else:
            excluded.append({
                "key": "propagation",
                "label": "Redistribution in local index",
                "reason": (
                    "No related media was found in the local evidence index, so redistribution "
                    "contributed nothing. This only covers cases stored in this instance."
                ),
            })
    else:
        excluded.append({
            "key": "propagation",
            "label": "Redistribution in local index",
            "reason": "Local copy tracing did not run for this case.",
        })

    # ── Weighted combination ─────────────────────────────────────────────────
    total_weight = sum(signal["weight"] for signal in signals)
    for signal in signals:
        share = signal["weight"] / total_weight if total_weight else 0.0
        signal["effective_weight"] = round(share, 4)
        signal["contribution"] = round(share * signal["normalized"], 6)

    score = sum(signal["contribution"] for signal in signals) if total_weight else 0.0
    score = max(0.0, min(1.0, score))
    level = _band(score)
    signals.sort(key=lambda s: s["contribution"], reverse=True)

    return {
        "overall_risk_score": round(score, 6),
        "risk_level": level,
        "signals_used": len(signals),
        "signals_excluded": len(excluded),
        "signals": signals,
        "excluded": excluded,
        "weights_declared": WEIGHTS,
        "total_declared_weight_available": round(total_weight, 4),
        "thresholds": {
            "face_cosine_same_person": FACE_THRESHOLD,
            "voice_cosine_same_speaker": VOICE_THRESHOLD,
            "manipulation_probability": MANIPULATION_THRESHOLD,
            "risk_bands": {"CRITICAL": 0.75, "HIGH": 0.50, "MEDIUM": 0.25, "LOW": 0.0},
        },
        "formula": (
            "risk = Σ(weightᵢ / Σweights_available × normalizedᵢ). Declared weights: "
            + ", ".join(f"{k} {v:.2f}" for k, v in WEIGHTS.items())
            + ". Weights are renormalised over the signals that were actually available, so an "
              "unavailable module neither raises nor lowers the score."
        ),
        "explanation": build_explanation(
            score, level, signals, excluded, deepfake, identity, localization,
            propagation, media_type, identity_name,
        ),
        "disclaimer": (
            "This score is an investigative prioritisation aid derived from forensic indicators. "
            "It is not proof of manipulation, not proof of identity, and not a legal determination. "
            "Findings require review by a qualified investigator."
        ),
    }


def build_explanation(score: float, level: str, signals: list[dict], excluded: list[dict],
                      deepfake: dict | None, identity: dict | None,
                      localization: dict | None, propagation: dict | None,
                      media_type: str, identity_name: str | None) -> str:
    """Natural-language rationale assembled from the values actually observed."""
    if not signals:
        return (
            "No forensic signal could be computed for this media, so no risk assessment was "
            "produced. Review the excluded-signal list for the reason each module did not run."
        )

    subject = (identity or {}).get("reference_identity") or identity_name
    sentences = [
        f"Assessed {level} impersonation risk ({score:.2f} on a 0–1 scale) from "
        f"{len(signals)} available forensic signal(s)."
    ]

    manipulation = next((s for s in signals if s["key"] == "manipulation"), None)
    if manipulation and deepfake:
        value = manipulation["raw_value"]
        suspicious = deepfake.get("suspicious_frame_count")
        analysed = deepfake.get("frames_analyzed")
        with_face = deepfake.get("frames_with_face")
        if media_type == "video" and analysed:
            fragment = (
                f"{deepfake.get('model_name', 'The manipulation detector')} returned a mean "
                f"manipulation signal of {value:.2f} across {analysed} sampled frame(s)"
            )
            if suspicious is not None:
                fragment += f", with {suspicious} frame(s) above the {MANIPULATION_THRESHOLD:.2f} threshold"
            if with_face is not None:
                fragment += f"; a face was located in {with_face} of them"
            sentences.append(fragment + ".")
        else:
            sentences.append(
                f"{deepfake.get('model_name', 'The manipulation detector')} returned a "
                f"manipulation signal of {value:.2f} for this media."
            )

        intervals = (localization or {}).get("suspicious_intervals") or []
        if intervals:
            windows = ", ".join(interval["label"] for interval in intervals[:3])
            sentences.append(
                f"The strongest manipulation evidence is concentrated in {len(intervals)} time "
                f"window(s): {windows}."
            )
        elif (localization or {}).get("status") == "completed" and not intervals \
                and localization.get("suspicious_frame_count") == 0:
            sentences.append(
                "No individual sampled frame crossed the suspicion threshold, so no specific "
                "time window is flagged."
            )

    identity_signal = next((s for s in signals if s["key"] == "identity"), None)
    if identity_signal:
        sentences.append(identity_signal["detail"])
    elif subject:
        sentences.append(
            f"Face comparison against {subject} did not produce a score, so this assessment does "
            "not establish whether the media depicts the protected identity."
        )

    voice_signal = next((s for s in signals if s["key"] == "voice"), None)
    if voice_signal:
        sentences.append(voice_signal["detail"])

    consistency_signal = next((s for s in signals if s["key"] == "av_consistency"), None)
    if consistency_signal and consistency_signal["normalized"] >= 0.4:
        sentences.append(consistency_signal["detail"])

    if propagation and (propagation.get("match_count") or 0) > 0:
        sentences.append(propagation.get("summary", ""))

    dominant = signals[0]
    sentences.append(
        f"The largest single contribution came from {dominant['label'].lower()} "
        f"({dominant['contribution']:.3f} of the {score:.2f} total, at an effective weight of "
        f"{dominant['effective_weight']:.2f})."
    )

    if excluded:
        names = ", ".join(item["label"].lower() for item in excluded[:4])
        sentences.append(
            f"{len(excluded)} signal(s) were unavailable and excluded rather than assumed "
            f"({names}); they neither raised nor lowered this score."
        )

    sentences.append(
        "These are forensic indicators for investigator review, not proof of manipulation or "
        "of identity."
    )
    return " ".join(part for part in sentences if part)
