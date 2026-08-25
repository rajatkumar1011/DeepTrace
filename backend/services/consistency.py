"""Audio/video consistency checks.

Two independent signals:

  1. **Presence alignment** — does a face appear in a sampled frame at the same
     moments the audio track carries speech-level energy?
  2. **Stream duration agreement** — do the video and audio streams cover the
     same span? A mismatch is a common artefact of re-muxed or overdubbed media.

This is a lightweight heuristic, not SyncNet or a deep multimodal verifier, and
it is labelled as such everywhere the result surfaces.
"""

import os

import cv2
import numpy as np

from services.forensics import load_audio_samples

_METHOD = "Face presence vs audio RMS windows + stream duration agreement"
_MODEL_STATUS = "Lightweight heuristic (not SyncNet or deep lip-sync verification)"


def _unavailable(reason: str, audio_present: bool | None = None) -> dict:
    return {
        "status": "unavailable",
        "consistency_score": None,
        "audio_present": audio_present,
        "face_present_ratio": None,
        "energy_alignment_score": None,
        "method": _METHOD,
        "model_status": _MODEL_STATUS,
        "details": reason,
        "excluded_from_risk": True,
    }


def _load_face_cascade():
    cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
    cascade = cv2.CascadeClassifier(cascade_path)
    return None if cascade.empty() else cascade


def _window_energies(audio_path: str, timestamps, window_seconds: float = 0.4):
    """RMS energy in a window centred on each frame timestamp."""
    samples, sample_rate = load_audio_samples(audio_path)
    if samples is None or not sample_rate:
        return None, "the decoded audio track could not be read as PCM samples"
    if samples.size == 0:
        return None, "the decoded audio track is empty"

    peak = float(np.max(np.abs(samples))) or 1.0
    samples = samples / peak
    half = int((window_seconds / 2.0) * sample_rate)
    energies = []
    for timestamp in timestamps:
        centre = int(float(timestamp) * sample_rate)
        chunk = samples[max(0, centre - half):min(len(samples), centre + half)]
        energies.append(float(np.sqrt(np.mean(chunk ** 2))) if chunk.size else 0.0)
    return energies, None


def check_av_consistency(video_path: str, frame_items: list | None = None,
                         audio_path: str | None = None,
                         probe_summary: dict | None = None) -> dict:
    """Compare sampled-frame face presence against audio energy at the same times.

    ``frame_items`` and ``audio_path`` are the artifacts the pipeline has already
    produced, so nothing is re-extracted here and no temporary files are created.
    """
    frame_items = frame_items or []
    audio_present = bool(audio_path) and os.path.isfile(audio_path)

    if not audio_present:
        return _unavailable(
            "No decoded audio track was available, so audio/video alignment could not be "
            "measured. This module was excluded from risk fusion.",
            audio_present=False,
        )
    if not frame_items:
        return _unavailable(
            "No sampled video frames were available, so audio/video alignment could not be "
            "measured. This module was excluded from risk fusion.",
            audio_present=True,
        )

    cascade = _load_face_cascade()
    if cascade is None:
        return _unavailable(
            "The OpenCV frontal-face cascade could not be loaded on this machine, so face "
            "presence could not be established.",
            audio_present=True,
        )

    timestamps: list[float] = []
    face_flags: list[bool] = []
    face_counts: list[int] = []
    for item in frame_items:
        path = item.get("path") if isinstance(item, dict) else item
        timestamp = float(item.get("timestamp", 0.0)) if isinstance(item, dict) else 0.0
        image = cv2.imread(path) if path else None
        if image is None:
            continue
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=4, minSize=(40, 40))
        timestamps.append(timestamp)
        face_flags.append(len(faces) > 0)
        face_counts.append(len(faces))

    if not timestamps:
        return _unavailable(
            "None of the sampled frames could be read back from disk for face detection.",
            audio_present=True,
        )

    energies, energy_error = _window_energies(audio_path, timestamps)
    if energy_error or energies is None:
        return _unavailable(f"Audio energy could not be measured: {energy_error}.", audio_present=True)

    # Threshold relative to the track's own median so quiet recordings are not
    # scored as silent throughout.
    energy_threshold = max(0.02, float(np.median(energies)) * 0.5)
    speaking_flags = [energy >= energy_threshold for energy in energies]
    aligned = sum(1 for face, speaking in zip(face_flags, speaking_flags) if face == speaking)
    alignment = aligned / len(timestamps)
    face_ratio = sum(1 for flag in face_flags if flag) / len(face_flags)

    mismatches = [
        {
            "timestamp_seconds": round(timestamp, 3),
            "face_present": face,
            "audio_active": speaking,
            "audio_rms": round(energy, 5),
            "observation": (
                "Audio carries speech-level energy while no face is visible in this sampled frame."
                if speaking and not face else
                "A face is visible while the audio is near-silent at this timestamp."
            ),
        }
        for timestamp, face, speaking, energy in zip(timestamps, face_flags, speaking_flags, energies)
        if face != speaking
    ]

    duration_check = _duration_agreement(probe_summary)

    observations = [
        f"A face was detected in {sum(face_flags)} of {len(face_flags)} sampled frames "
        f"({face_ratio * 100:.0f}%).",
        f"Face presence and audio activity agreed at {aligned} of {len(timestamps)} sampled "
        f"timestamps ({alignment * 100:.0f}%).",
    ]
    if mismatches:
        observations.append(
            f"{len(mismatches)} timestamp(s) disagreed — see the mismatch list for the specific times."
        )
    if duration_check.get("observation"):
        observations.append(duration_check["observation"])

    return {
        "status": "completed",
        "consistency_score": round(alignment, 4),
        "audio_present": True,
        "face_present_ratio": round(face_ratio, 4),
        "energy_alignment_score": round(alignment, 4),
        "energy_threshold": round(energy_threshold, 5),
        "samples_compared": len(timestamps),
        "faces_detected_total": int(sum(face_counts)),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:10],
        "duration_agreement": duration_check,
        "observations": observations,
        "method": _METHOD,
        "model_status": _MODEL_STATUS,
        "details": (
            "Alignment is the share of sampled timestamps where face presence and audio energy "
            "agree. Low alignment is expected for legitimate media such as voice-overs, "
            "reaction shots and B-roll, so it is a supporting signal only."
        ),
        "warning": "This is a supporting forensic signal, not proof of manipulation.",
        "excluded_from_risk": False,
    }


def _duration_agreement(probe_summary: dict | None) -> dict:
    """Compare declared video and audio stream durations."""
    if not probe_summary:
        return {
            "status": "unavailable",
            "reason": "Container stream durations were not available (FFprobe metadata missing).",
        }
    video_duration = probe_summary.get("video_duration_seconds") or probe_summary.get("duration_seconds")
    audio_duration = probe_summary.get("audio_duration_seconds")
    if not video_duration or not audio_duration:
        return {
            "status": "unavailable",
            "reason": "The container did not declare both a video and an audio duration.",
        }

    delta = abs(float(video_duration) - float(audio_duration))
    longest = max(float(video_duration), float(audio_duration))
    relative = delta / longest if longest else 0.0
    # 0.5 s / 2 % tolerates ordinary encoder frame-boundary padding.
    mismatch = delta > 0.5 and relative > 0.02
    return {
        "status": "completed",
        "video_duration_seconds": round(float(video_duration), 3),
        "audio_duration_seconds": round(float(audio_duration), 3),
        "delta_seconds": round(delta, 3),
        "relative_delta": round(relative, 4),
        "mismatch": mismatch,
        "observation": (
            f"Video and audio stream durations differ by {delta:.2f}s ({relative * 100:.1f}%), "
            "which can occur when a track has been re-muxed or overdubbed."
            if mismatch else
            f"Video and audio stream durations agree to within {delta:.2f}s."
        ),
    }
