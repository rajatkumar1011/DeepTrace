"""Manipulation localization.

Turns per-frame detector output into *where* and *when*:

  • which sampled frames carry the strongest manipulation evidence,
  • the time intervals those frames fall into,
  • the face region within each frame,
  • a residual-overlay image per suspicious frame.

The overlay is an explainable image-forensics visualisation (high-frequency
residual, where blending and re-compression artefacts concentrate), not a trained
segmentation mask. That distinction is stated in the payload and carried through
to the UI and the PDF report.
"""

import os

from services.forensics import save_residual_overlay

SUSPICION_THRESHOLD = 0.5
MAX_OVERLAYS = 6


def _format_timestamp(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    minutes, secs = divmod(float(seconds), 60)
    return f"{int(minutes):02d}:{secs:05.2f}"


def _merge_intervals(timestamps: list[float], span: float) -> list[dict]:
    """Group nearby suspicious timestamps into contiguous intervals.

    ``span`` is the sampling interval, so two consecutive suspicious samples are
    treated as one continuous stretch rather than two separate events.
    """
    if not timestamps:
        return []
    ordered = sorted(timestamps)
    gap = max(span * 1.5, 0.5)
    intervals: list[dict] = []
    start = previous = ordered[0]
    count = 1
    for current in ordered[1:]:
        if current - previous <= gap:
            previous = current
            count += 1
            continue
        intervals.append({"start_seconds": round(start, 3), "end_seconds": round(previous, 3),
                          "sample_count": count})
        start = previous = current
        count = 1
    intervals.append({"start_seconds": round(start, 3), "end_seconds": round(previous, 3),
                      "sample_count": count})
    for interval in intervals:
        interval["label"] = (
            f"{_format_timestamp(interval['start_seconds'])} – {_format_timestamp(interval['end_seconds'])}"
        )
        interval["duration_seconds"] = round(interval["end_seconds"] - interval["start_seconds"], 3)
    return intervals


def localize(deepfake_result: dict | None, media_type: str, output_dir: str,
             threshold: float = SUSPICION_THRESHOLD) -> dict:
    """Build the localization payload from an existing deepfake analysis result."""
    if not deepfake_result or not deepfake_result.get("frame_results"):
        return {
            "status": "unavailable",
            "reason": "No per-frame manipulation scores were available to localize.",
            "method": "Frame ranking + high-frequency residual overlay",
        }

    frames = deepfake_result["frame_results"]
    ranked = sorted(frames, key=lambda f: float(f.get("manipulation_signal") or 0.0), reverse=True)
    suspicious = [f for f in ranked if float(f.get("manipulation_signal") or 0.0) >= threshold]

    timestamps = [
        float(f["frame_timestamp_seconds"]) for f in frames
        if f.get("frame_timestamp_seconds") is not None
    ]
    sampling_span = 0.0
    if len(timestamps) > 1:
        ordered = sorted(timestamps)
        gaps = [b - a for a, b in zip(ordered, ordered[1:])]
        sampling_span = sum(gaps) / len(gaps)

    suspicious_timestamps = [
        float(f["frame_timestamp_seconds"]) for f in suspicious
        if f.get("frame_timestamp_seconds") is not None
    ]
    intervals = _merge_intervals(suspicious_timestamps, sampling_span) if media_type == "video" else []
    for interval in intervals:
        # Strongest score observed inside the window, so an investigator can rank
        # which flagged stretch to review first.
        inside = [
            float(f.get("manipulation_signal") or 0.0) for f in suspicious
            if f.get("frame_timestamp_seconds") is not None
            and interval["start_seconds"] <= float(f["frame_timestamp_seconds"]) <= interval["end_seconds"]
        ]
        interval["peak_signal"] = round(max(inside), 4) if inside else None

    # Overlays are produced for the strongest frames only — enough to show the
    # investigator where to look without writing an image per sampled frame.
    overlays: list[dict] = []
    targets = (suspicious or ranked)[:MAX_OVERLAYS]
    os.makedirs(output_dir, exist_ok=True)
    for rank, frame in enumerate(targets, start=1):
        source = frame.get("frame_path")
        if not source or not os.path.isfile(source):
            continue
        stem = os.path.splitext(os.path.basename(source))[0]
        dest = os.path.join(output_dir, f"residual_{rank:02d}_{stem}.jpg")
        written = save_residual_overlay(source, dest)
        if not written:
            continue
        overlays.append({
            "rank": rank,
            "source_frame": source,
            "overlay_path": written,
            "manipulation_signal": round(float(frame.get("manipulation_signal") or 0.0), 4),
            "timestamp_seconds": frame.get("frame_timestamp_seconds"),
            "timestamp_label": _format_timestamp(frame.get("frame_timestamp_seconds")),
            "face_box": frame.get("face_box"),
            "face_detected": bool(frame.get("face_detected")),
            "face_source": frame.get("face_source"),
        })

    top_regions = [
        {
            "timestamp_seconds": frame.get("frame_timestamp_seconds"),
            "timestamp_label": _format_timestamp(frame.get("frame_timestamp_seconds")),
            "manipulation_signal": round(float(frame.get("manipulation_signal") or 0.0), 4),
            "face_box_xyxy": frame.get("face_box"),
            "face_detected": bool(frame.get("face_detected")),
            "face_source": frame.get("face_source"),
            "region_note": (
                "Scored region is the detected face plus a 30% margin."
                if frame.get("face_detected") else
                "No face located; the whole frame was scored."
            ),
        }
        for frame in ranked[:10]
    ]

    if suspicious:
        if media_type == "video" and intervals:
            windows = ", ".join(interval["label"] for interval in intervals[:4])
            summary = (
                f"{len(suspicious)} of {len(frames)} sampled frames scored at or above "
                f"{threshold:.2f}, concentrated in {len(intervals)} time window(s): {windows}."
            )
        else:
            summary = (
                f"{len(suspicious)} of {len(frames)} analysed region(s) scored at or above "
                f"{threshold:.2f}."
            )
    else:
        summary = (
            f"No sampled frame reached the {threshold:.2f} suspicion threshold. The strongest "
            f"frame scored {float(ranked[0].get('manipulation_signal') or 0.0):.3f}"
            + (f" at {_format_timestamp(ranked[0].get('frame_timestamp_seconds'))}."
               if ranked[0].get("frame_timestamp_seconds") is not None else ".")
        )

    return {
        "status": "completed",
        "method": "Frame ranking + high-frequency residual overlay",
        "model_status": "Localization derives from the manipulation detector's per-frame scores",
        "threshold": threshold,
        "frames_examined": len(frames),
        "suspicious_frame_count": len(suspicious),
        "sampling_interval_seconds": round(sampling_span, 3) if sampling_span else None,
        "suspicious_intervals": intervals,
        "suspicious_timestamps": [round(t, 3) for t in sorted(suspicious_timestamps)],
        "suspicious_timestamp_labels": [_format_timestamp(t) for t in sorted(suspicious_timestamps)],
        "top_regions": top_regions,
        "overlays": overlays,
        "summary": summary,
        "interpretation": (
            (
                "Timestamps mark sampled frames whose manipulation score crossed the threshold; "
                "unsampled frames between them were not examined. "
            ) if suspicious else (
                "No sampled frame crossed the manipulation threshold. The overlays show the "
                "highest-scoring sampled frames for investigator review; they are not being "
                "described as threshold-crossing findings. "
            )
        ) + (
            "Overlay images visualise high-frequency residual energy — where blending and "
            "re-compression artefacts concentrate — and are an explainable forensic aid, not a "
            "trained segmentation mask."
        ),
    }
