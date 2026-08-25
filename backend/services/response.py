"""Response and reporting guidance.

Generates the "what do I do now" section of a case from the case's own facts.

Boundary that must not blur: DeepTrace prepares material and explains the
available routes. It does not file complaints, does not contact platforms, does
not submit anything to law enforcement, and has no legal authority. Every
generated action is phrased as something the investigator or affected person
does, with DeepTrace supplying the evidence package.
"""

PRIORITY_BY_RISK = {
    "CRITICAL": "Immediate",
    "HIGH": "Urgent",
    "MEDIUM": "Standard",
    "LOW": "Routine",
}

# Public reporting routes in India. Listed as information for the affected person
# to use themselves — DeepTrace does not contact any of these on their behalf.
REPORTING_ROUTES = [
    {
        "route": "National Cyber Crime Reporting Portal",
        "detail": "cybercrime.gov.in — the Government of India portal for reporting cybercrime, "
                  "including a dedicated category for obscene or impersonating content.",
        "who_acts": "The affected person or their authorised representative files the complaint.",
    },
    {
        "route": "Cyber Crime Helpline 1930",
        "detail": "National helpline for cyber-financial and cybercrime assistance.",
        "who_acts": "The affected person calls; DeepTrace cannot place the call.",
    },
    {
        "route": "Local police / cyber cell",
        "detail": "An FIR or written complaint at the jurisdictional police station or cyber cell, "
                  "with the exported report and preserved media attached.",
        "who_acts": "The affected person or investigating officer.",
    },
    {
        "route": "Platform trust & safety / grievance officer",
        "detail": "Most platforms operating in India publish a grievance officer contact and an "
                  "impersonation or synthetic-media reporting form.",
        "who_acts": "The affected person submits the platform's own report form.",
    },
]


def _fmt_interval(interval: dict) -> str:
    return interval.get("label") or f"{interval.get('start_seconds')}s–{interval.get('end_seconds')}s"


def build_guidance(*, investigation: dict, risk: dict | None, deepfake: dict | None,
                   identity: dict | None, voice: dict | None, localization: dict | None,
                   propagation: dict | None, provenance: dict | None,
                   trace_sources: list[dict] | None, integrity: dict | None) -> dict:
    """Assemble case-specific guidance. Every item references an observed fact."""
    risk_level = (risk or {}).get("risk_level") or investigation.get("risk_level") or "UNKNOWN"
    priority = PRIORITY_BY_RISK.get(risk_level, "Standard")
    identity_name = (identity or {}).get("reference_identity")
    trace_sources = trace_sources or []

    findings: list[str] = []
    actions: list[dict] = []

    # ── Case-specific findings that drive the actions ────────────────────────
    manipulation_signal = (deepfake or {}).get("manipulation_signal")
    if manipulation_signal is not None:
        findings.append(
            f"Manipulation signal {float(manipulation_signal):.2f} from "
            f"{(deepfake or {}).get('model_name', 'the manipulation detector')}."
        )
    intervals = (localization or {}).get("suspicious_intervals") or []
    if intervals:
        findings.append(
            f"{len(intervals)} flagged time window(s): "
            + ", ".join(_fmt_interval(i) for i in intervals[:4]) + "."
        )
    best_face = (identity or {}).get("best_similarity")
    if best_face is not None and identity_name:
        findings.append(f"Face similarity to {identity_name}: {float(best_face):.2f}.")
    if (voice or {}).get("status") == "completed" and voice.get("voice_match_score") is not None:
        findings.append(f"Speaker similarity to the enrolled reference: {float(voice['voice_match_score']):.2f}.")
    if (propagation or {}).get("match_count"):
        findings.append(propagation.get("summary", ""))

    # ── Actions ──────────────────────────────────────────────────────────────
    actions.append({
        "step": 1,
        "action": "Preserve the evidence package before anything else changes",
        "why": (
            "The original media, sampled frames and their SHA-256 digests are already preserved "
            "locally. Export the PDF report now so the case state is captured with its hashes."
            + (f" Integrity check at last run: {integrity.get('summary')}" if integrity and integrity.get("summary") else "")
        ),
        "who_acts": "Investigator, using DeepTrace's report export.",
        "deeptrace_role": "Generates and hashes the package. DeepTrace does not transmit it anywhere.",
    })

    if intervals:
        actions.append({
            "step": len(actions) + 1,
            "action": "Manually review the flagged time windows",
            "why": (
                "The detector flagged " + ", ".join(_fmt_interval(i) for i in intervals[:4])
                + ". Human review of these specific segments is what converts a model score into "
                  "a defensible finding — the score alone is not sufficient."
            ),
            "who_acts": "Investigator or forensic examiner.",
            "deeptrace_role": "Supplies the timestamps, frame images and residual overlays.",
        })
    elif manipulation_signal is not None:
        actions.append({
            "step": len(actions) + 1,
            "action": "Review the sampled frames manually",
            "why": (
                "No individual frame crossed the suspicion threshold. Manual review is still "
                "required before drawing any conclusion, because sampling examines only a subset "
                "of frames."
            ),
            "who_acts": "Investigator or forensic examiner.",
            "deeptrace_role": "Supplies the sampled frames and per-frame scores.",
        })

    if identity_name and best_face is not None:
        if float(best_face) >= 0.60:
            actions.append({
                "step": len(actions) + 1,
                "action": f"Confirm with {identity_name} that this media is not genuine",
                "why": (
                    f"Face similarity of {float(best_face):.2f} is above the same-person threshold, so "
                    "the media appears to depict them. A first-person statement that the content is "
                    "fabricated carries more weight in a complaint than a model score."
                ),
                "who_acts": "Investigator, in contact with the affected person.",
                "deeptrace_role": "Provides the comparison score and the reference used.",
            })
        else:
            actions.append({
                "step": len(actions) + 1,
                "action": "Re-check the identity assumption before escalating",
                "why": (
                    f"Face similarity of {float(best_face):.2f} is below the 0.60 same-person threshold. "
                    "Either the media does not depict the enrolled identity, or the reference image is "
                    "unsuitable (pose, lighting, resolution). Re-enroll with a clear frontal image "
                    "before treating this as an impersonation case."
                ),
                "who_acts": "Investigator.",
                "deeptrace_role": "Flags the weak match rather than asserting a match.",
            })
    elif not identity_name:
        actions.append({
            "step": len(actions) + 1,
            "action": "Enroll the affected person as a protected identity and re-run",
            "why": (
                "No identity was attached to this case, so DeepTrace measured manipulation without "
                "establishing whom the media depicts. Impersonation findings need both halves."
            ),
            "who_acts": "Investigator, with the affected person's consent.",
            "deeptrace_role": "Performs the comparison once a consented reference exists.",
        })

    if (voice or {}).get("status") == "not_applicable":
        actions.append({
            "step": len(actions) + 1,
            "action": "Collect a reference voice sample if the audio matters to the case",
            "why": (
                "The media contains audio but no reference voice is enrolled, so speaker comparison "
                "could not run. A 10–30 second clear sample enables it."
            ),
            "who_acts": "Investigator, with consent from the affected person.",
            "deeptrace_role": "Runs speaker verification once a reference exists.",
        })

    if trace_sources:
        fetched = [s for s in trace_sources if s.get("retrieval_status") == "fetched"]
        actions.append({
            "step": len(actions) + 1,
            "action": "Submit platform takedown requests for the recorded source URLs",
            "why": (
                f"{len(trace_sources)} source URL(s) are attached to this case"
                + (f", {len(fetched)} of which were retrieved and hash-matched against the original."
                   if fetched else ", none of which could be retrieved.")
                + " Platform grievance channels act on specific URLs, and each preserved copy "
                  "supports the request."
            ),
            "who_acts": "The affected person or their representative submits the request.",
            "deeptrace_role": "Preserved the retrieved copies and computed the similarity to the original.",
        })
    else:
        actions.append({
            "step": len(actions) + 1,
            "action": "Record where the media was found",
            "why": (
                "No source URL is attached to this case. Takedown and reporting channels operate on "
                "specific URLs, so capturing where the content appeared is necessary for any "
                "platform-side action."
            ),
            "who_acts": "Investigator or the person who encountered the content.",
            "deeptrace_role": "Retrieves and preserves a copy from a supplied public URL.",
        })

    if (propagation or {}).get("match_count"):
        actions.append({
            "step": len(actions) + 1,
            "action": "Link the related cases in this instance",
            "why": propagation.get("summary", "") + " Treating them as one incident avoids duplicate work "
                   "and shows a pattern of redistribution.",
            "who_acts": "Investigator.",
            "deeptrace_role": "Identified the matching cases by hash.",
        })

    if risk_level in {"CRITICAL", "HIGH"}:
        actions.append({
            "step": len(actions) + 1,
            "action": "Escalate for formal reporting",
            "why": (
                f"Risk was assessed {risk_level}. The routes below are the available reporting "
                "channels; DeepTrace cannot file with any of them."
            ),
            "who_acts": "The affected person or an authorised officer.",
            "deeptrace_role": "Supplies the exported report and preserved evidence to attach.",
        })

    package = [
        "Exported DeepTrace PDF report (contains hashes, per-module findings and stated limitations)",
        "Original submitted media, unmodified, with its recorded SHA-256",
    ]
    if (investigation.get("frames_extracted") or 0) > 0:
        package.append(f"{investigation['frames_extracted']} preserved sampled frames with individual SHA-256 digests")
    if intervals:
        package.append("Residual-overlay images for the flagged frames")
    if (voice or {}).get("status") == "completed":
        package.append("Extracted audio track with its SHA-256 digest")
    if trace_sources:
        package.append(f"{len(trace_sources)} recorded source URL(s) and any retrieved copies")
    package.append("Case timeline showing when each step ran")

    return {
        "priority": priority,
        "risk_level": risk_level,
        "case_findings": [f for f in findings if f],
        "recommended_actions": actions,
        "evidence_package": package,
        "reporting_routes": REPORTING_ROUTES,
        "deeptrace_boundary": (
            "DeepTrace prepares and preserves evidence and explains the available routes. It does "
            "not file complaints, does not contact platforms or authorities, does not remove "
            "content, and does not identify who created the media. All outward action is taken by "
            "the affected person or an authorised officer."
        ),
        "caveats": [
            "Model outputs are forensic indicators, not proof of manipulation or of identity.",
            "DeepTrace does not identify the creator or uploader of the media.",
            "Hash-based preservation demonstrates local integrity; it is not third-party "
            "notarisation and does not by itself establish legal admissibility.",
            "Sampling examines a subset of frames; segments between samples were not analysed.",
        ],
    }
