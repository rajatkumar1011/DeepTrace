"""Measure how DeepTrace's detectors behave on degraded copies of the same file.

Why this is separate from ``scripts/benchmark.py``: accuracy needs labelled data,
robustness does not. Every figure here is a *paired* comparison of one file
against a transformed copy of itself, so the ground truth is structural — the
content is identical, only the encoding changed. That makes this the one
validation we can run honestly without a labelled corpus, and it answers the
question an investigator actually faces: the media arrived as a WhatsApp
forward, or a screen recording of someone else's screen, so is the score still
worth anything?

What is measured, per file and per transform:

    baseline score      the real pipeline's score on the original
    degraded score      the real pipeline's score on the ffmpeg-transformed copy
    delta               degraded - baseline
    decision agreement  whether both land on the same side of the threshold

and, aggregated per transform, the mean absolute delta and the share of files
whose decision survived. Decision agreement is the number that matters: a score
that moves 0.05 but never crosses the threshold changes no conclusion, while one
that moves 0.05 across the threshold changes every conclusion.

The transforms are real ffmpeg operations, not synthetic noise. Their limits are
stated in the output: a re-encode of a video reproduces what a platform's
transcoder does to it, and a downscale-pad-resample chain reproduces the
geometry and encoding of a screen capture, but neither reproduces panel moire,
capture-card colour handling, or the recompression history of a file that has
already been round-tripped by a platform we do not have.

Sources, in order of preference (nothing is downloaded):

    --media <path>                      one or more explicit files
    data/benchmark/robustness_source/   drop authentic media here
    data/benchmark/dataset/             the benchmark set, if one is present
    data/demo/ and data/test_video.mp4  the repository's demo inputs

Usage:
    backend/venv/Scripts/python.exe scripts/robustness.py
    backend/venv/Scripts/python.exe scripts/robustness.py --media data/test_video.mp4 --frames 8

Exit codes: 0 evaluated and written, 3 nothing to evaluate, 4 ffmpeg unavailable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

from paths import BENCHMARK_DIR  # noqa: E402
from services import audio as audio_service  # noqa: E402
from services import deepfake, forensics  # noqa: E402

ROBUSTNESS_JSON = os.path.join(BENCHMARK_DIR, "robustness.json")
SOURCE_DIR = os.path.join(BENCHMARK_DIR, "robustness_source")

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_EXT = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"}

DEFAULT_THRESHOLD = 0.50
FFMPEG_TIMEOUT = 300

# Baselines inside this band of the threshold are marked: a decision flip there
# is a property of the borderline case, not evidence that the transform broke the
# detector, and the aggregate reports both figures so neither reading dominates.
NEAR_THRESHOLD = 0.05

# Below this duration the audio editing indicator's per-minute discontinuity rate
# is extrapolated from so little material that a single transition saturates it.
SHORT_AUDIO_SECONDS = 10.0

NOTHING_TO_EVALUATE_EXIT = 3
NO_FFMPEG_EXIT = 4


# --------------------------------------------------------------------------- #
# the transforms
#
# Each entry is (key, human label, what real-world event it stands for, argv
# tail). The argv tail is spliced between "-i <input>" and the output path, so
# every transform is one ffmpeg invocation with an explicit codec and no shell.
# --------------------------------------------------------------------------- #

VIDEO_TRANSFORMS = [
    {
        "key": "recompress_crf28",
        "label": "H.264 re-encode at CRF 28",
        "stands_for": "One round of ordinary platform recompression, resolution unchanged.",
        "args": ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "28", "-preset", "veryfast"],
        "audio_args": ["-c:a", "copy"],
        "family": "compression",
    },
    {
        "key": "recompress_crf36",
        "label": "H.264 re-encode at CRF 36",
        "stands_for": "Aggressive compression, the quality floor of a heavily re-shared clip.",
        "args": ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "36", "-preset", "veryfast"],
        "audio_args": ["-c:a", "copy"],
        "family": "compression",
    },
    {
        "key": "downscale_360p",
        "label": "Downscale to 360p",
        "stands_for": "Resolution loss alone, holding the encoder quality high, to separate the "
                      "effect of fewer pixels from the effect of compression artefacts.",
        "args": ["-vf", "scale=-2:360", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "veryfast"],
        "audio_args": ["-c:a", "copy"],
        "family": "resolution",
    },
    {
        "key": "messaging_reupload",
        "label": "Messaging-app re-upload (480p, CRF 30, AAC 64k)",
        "stands_for": "The transcode a chat application applies when a video is forwarded: "
                      "downscale, re-encode, re-encode the audio, strip metadata.",
        "args": ["-vf", "scale=-2:480", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "30", "-preset", "veryfast",
                 "-profile:v", "baseline", "-map_metadata", "-1"],
        "audio_args": ["-c:a", "aac", "-b:a", "64k", "-ar", "44100"],
        "family": "reupload",
    },
    {
        "key": "screen_recording",
        "label": "Screen recording of a playing window",
        "stands_for": "Media captured by pointing a screen recorder at a playback window: the "
                      "video is scaled into a 1280x720 canvas with letterboxing, resampled to a "
                      "fixed 30 fps, shifted slightly by display gamma, and re-encoded.",
        "args": ["-vf", "scale=1120:-2:flags=bicubic,pad=1280:720:(ow-iw)/2:(oh-ih)/2:black,"
                        "eq=brightness=0.02:contrast=1.04:saturation=0.98,fps=30",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "26", "-preset", "veryfast", "-map_metadata", "-1"],
        "audio_args": ["-c:a", "aac", "-b:a", "128k", "-ar", "44100"],
        "family": "screen_capture",
    },
]

# Applied twice, in sequence, to model a file that has been round-tripped by a
# platform more than once. Listed separately because it is a chain, not a call.
VIDEO_CHAINS = [
    {
        "key": "double_reupload",
        "label": "Two rounds of messaging-app re-upload",
        "stands_for": "Downloaded and re-shared: the platform transcode applied to its own output, "
                      "which is what most forwarded evidence has actually been through.",
        "steps": ["messaging_reupload", "messaging_reupload"],
        "family": "reupload",
    },
    {
        "key": "screen_recording_of_reupload",
        "label": "Screen recording of an already re-uploaded copy",
        "stands_for": "The worst realistic case for a victim's evidence: the clip was forwarded "
                      "through a chat app, then screen-recorded off a phone or monitor.",
        "steps": ["messaging_reupload", "screen_recording"],
        "family": "screen_capture",
    },
]

IMAGE_TRANSFORMS = [
    {
        "key": "jpeg_q75",
        "label": "JPEG re-encode at quality 75",
        "stands_for": "Ordinary recompression on save or upload.",
        "args": ["-q:v", "6"],
        "family": "compression",
        "suffix": ".jpg",
    },
    {
        "key": "jpeg_q40",
        "label": "JPEG re-encode at quality 40",
        "stands_for": "Heavy recompression, visible blocking.",
        "args": ["-q:v", "16"],
        "family": "compression",
        "suffix": ".jpg",
    },
    {
        "key": "messaging_reupload",
        "label": "Messaging-app re-upload (1024 px long edge, JPEG q65)",
        "stands_for": "The resize-and-recompress a chat application applies to a shared photo, "
                      "including metadata stripping.",
        "args": ["-vf", "scale='min(1024,iw)':-2", "-q:v", "10", "-map_metadata", "-1"],
        "family": "reupload",
        "suffix": ".jpg",
    },
    {
        "key": "screenshot",
        "label": "Screenshot of the image displayed on a 1280x720 screen",
        "stands_for": "Someone photographed or screen-captured the image rather than forwarding "
                      "the file: it is scaled into a screen-shaped canvas, letterboxed and "
                      "re-encoded, so the original pixel grid is gone.",
        "args": ["-vf", "scale=-2:640:flags=bicubic,pad=1280:720:(ow-iw)/2:(oh-ih)/2:black,"
                        "eq=brightness=0.02:contrast=1.04",
                 "-q:v", "8", "-map_metadata", "-1"],
        "family": "screen_capture",
        "suffix": ".jpg",
    },
]

IMAGE_CHAINS = [
    {
        "key": "double_reupload",
        "label": "Two rounds of messaging-app re-upload",
        "stands_for": "Shared, saved and shared again.",
        "steps": ["messaging_reupload", "messaging_reupload"],
        "family": "reupload",
    },
]

AUDIO_TRANSFORMS = [
    {
        "key": "aac_64k",
        "label": "AAC at 64 kbps",
        "stands_for": "The audio bitrate a chat application re-encodes a voice note to.",
        "args": ["-c:a", "aac", "-b:a", "64k", "-ar", "44100"],
        "family": "compression",
        "suffix": ".m4a",
    },
    {
        "key": "mp3_96k",
        "label": "MP3 at 96 kbps",
        "stands_for": "A lossy round-trip through the most common shared-audio format.",
        "args": ["-c:a", "libmp3lame", "-b:a", "96k", "-ar", "44100"],
        "family": "compression",
        "suffix": ".mp3",
    },
    {
        "key": "narrowband_8k",
        "label": "Resample to 8 kHz narrowband",
        "stands_for": "Audio that has been through a telephone or VoIP leg, which removes "
                      "everything above 4 kHz.",
        "args": ["-c:a", "pcm_s16le", "-ar", "8000", "-ac", "1"],
        "family": "resolution",
        "suffix": ".wav",
    },
    {
        "key": "screen_recording_audio",
        "label": "Screen-recorder audio path (44.1 kHz AAC 128k after a resample)",
        "stands_for": "Audio captured by a screen recorder rather than taken from the file: "
                      "resampled by the mixer, then encoded by the recorder.",
        "args": ["-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-af", "aresample=48000"],
        "family": "screen_capture",
        "suffix": ".m4a",
    },
]


# --------------------------------------------------------------------------- #
# ffmpeg
# --------------------------------------------------------------------------- #

def run_ffmpeg(source: str, dest: str, tail: list[str]) -> tuple[bool, str | None]:
    """One ffmpeg invocation, no shell, explicit argv, bounded time."""
    command = [forensics.ffmpeg_binary("ffmpeg"), "-y", "-nostdin", "-loglevel", "error",
               "-i", source] + list(tail) + [dest]
    try:
        completed = subprocess.run(command, capture_output=True, timeout=FFMPEG_TIMEOUT,
                                   shell=False, check=False)
    except subprocess.TimeoutExpired:
        return False, f"ffmpeg did not finish within {FFMPEG_TIMEOUT} s."
    except OSError as error:
        return False, f"ffmpeg could not be launched: {str(error)[:160]}"

    if completed.returncode != 0:
        detail = (completed.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        return False, (detail[-1] if detail else f"ffmpeg exited {completed.returncode}")[:240]
    if not os.path.isfile(dest) or os.path.getsize(dest) == 0:
        return False, "ffmpeg reported success but produced no output."
    return True, None


def visual_args(transform: dict, source_has_audio: bool) -> list[str]:
    """The argv tail for a visual transform, with the audio branch resolved.

    A silent video plus ``-c:a aac`` makes ffmpeg declare an audio output stream
    that never receives a packet, and it then refuses to write the file at all.
    Asking for ``-an`` when there is nothing to encode keeps the transform
    applicable to silent media instead of failing it as unsupported.
    """
    if not transform.get("audio_args"):
        return list(transform["args"])
    return list(transform["args"]) + (list(transform["audio_args"]) if source_has_audio else ["-an"])


def apply_chain(source: str, workspace: str, steps: list[dict], key: str,
                suffix: str, source_has_audio: bool) -> tuple[str | None, str | None]:
    """Run transforms back to back, each on the previous output."""
    current = source
    for index, step in enumerate(steps):
        dest = os.path.join(workspace, f"{key}_step{index}{suffix}")
        ok, reason = run_ffmpeg(current, dest, visual_args(step, source_has_audio))
        if not ok:
            return None, f"step {index + 1} ({step['key']}): {reason}"
        current = dest
    return current, None


# --------------------------------------------------------------------------- #
# scoring, through the real services
# --------------------------------------------------------------------------- #

def score_visual(path: str, frames: int) -> dict:
    """Manipulation signal for an image or video, via the services the API uses."""
    extension = os.path.splitext(path)[1].lower()

    if extension in IMAGE_EXT:
        result = deepfake.analyze_image(path)
        if not result or result.get("manipulation_signal") is None:
            return {"ok": False, "reason": "The manipulation model returned no score."}
        return {"ok": True, "score": float(result["manipulation_signal"]),
                "face_detected": bool(result.get("face_detected")),
                "frames_scored": 1, "method": result.get("method")}

    if extension in VIDEO_EXT:
        workspace = tempfile.mkdtemp(prefix="deeptrace_rob_frames_")
        try:
            sampled = forensics.extract_sampled_frames(path, workspace, num_samples=frames)
            if not sampled:
                return {"ok": False, "reason": "No frames could be decoded."}
            aggregate = deepfake.analyze_frames(sampled)
            if not aggregate or aggregate.get("manipulation_signal") is None:
                return {"ok": False, "reason": "The manipulation model returned no score for the frames."}
            per_frame = aggregate.get("frame_results") or []
            return {"ok": True, "score": float(aggregate["manipulation_signal"]),
                    "face_detected": any(item.get("face_detected") for item in per_frame),
                    "frames_scored": len(per_frame), "method": aggregate.get("method")}
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    return {"ok": False, "reason": f"Unsupported extension {extension} for visual scoring."}


def score_audio(path: str) -> dict:
    """Editing indicator for the audio in ``path``, decoded the way the pipeline does."""
    workspace = tempfile.mkdtemp(prefix="deeptrace_rob_audio_")
    try:
        decoded = os.path.join(workspace, "track.wav")
        ok, reason = audio_service.extract_audio_track(path, decoded)
        if not ok:
            return {"ok": False, "reason": reason or "No decodable audio stream."}
        result = audio_service.analyze_audio(decoded, forensics.probe_media(path))
        if result.get("status") != "completed":
            return {"ok": False, "reason": result.get("reason") or "Audio analysis was unavailable."}
        return {
            "ok": True,
            "score": float(result["editing_indicator"]),
            "duration_seconds": result.get("decoded_duration_seconds"),
            "discontinuities_per_minute": result.get("discontinuities_per_minute"),
            "clipping_ratio": (result.get("levels") or {}).get("clipping_ratio"),
            "mean_rolloff85_hz": (result.get("spectral") or {}).get("mean_rolloff85_hz"),
            "method": result.get("method"),
        }
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def has_audio(path: str) -> bool:
    if os.path.splitext(path)[1].lower() in AUDIO_EXT:
        return True
    probe = forensics.probe_media(path)
    if not probe:
        return False
    return any(stream.get("codec_type") == "audio" for stream in probe.get("streams", []))


# --------------------------------------------------------------------------- #
# one file, every transform
# --------------------------------------------------------------------------- #

def comparison(baseline: float, degraded: float, threshold: float) -> dict:
    """The paired result, with the decision agreement stated separately.

    Both are reported because they answer different questions. The delta says how
    far the score moved; the agreement says whether that movement changed the
    conclusion an investigator would draw. A large delta that stays on one side
    of the threshold is tolerable; a small one that crosses it is not.

    ``baseline_margin`` is carried alongside so the agreement figure cannot be
    over-read in either direction. A file whose original score sits 0.01 from the
    threshold will flip under almost any transform, and reporting that as a
    robustness failure without the margin would blame the transform for what is
    really a borderline case.
    """
    baseline_flag = baseline >= threshold
    degraded_flag = degraded >= threshold
    return {
        "baseline_score": round(baseline, 4),
        "degraded_score": round(degraded, 4),
        "baseline_margin": round(abs(baseline - threshold), 4),
        "delta": round(degraded - baseline, 4),
        "absolute_delta": round(abs(degraded - baseline), 4),
        "relative_delta_percent": (round((degraded - baseline) / baseline * 100, 1)
                                   if baseline > 1e-9 else None),
        "baseline_above_threshold": baseline_flag,
        "degraded_above_threshold": degraded_flag,
        "decision_preserved": baseline_flag == degraded_flag,
        "decision_change": (None if baseline_flag == degraded_flag
                            else ("flagged_to_cleared" if baseline_flag else "cleared_to_flagged")),
        # A flip is only attributable to the transform when the original was not
        # already sitting on the threshold. NEAR_THRESHOLD is the band inside
        # which the flip says more about the case than about the degradation.
        "baseline_near_threshold": abs(baseline - threshold) < NEAR_THRESHOLD,
    }


def evaluate_file(path: str, frames: int, threshold: float, include_audio: bool) -> dict:
    extension = os.path.splitext(path)[1].lower()
    is_video = extension in VIDEO_EXT
    is_image = extension in IMAGE_EXT
    is_audio_only = extension in AUDIO_EXT

    record: dict = {
        "file": os.path.basename(path),
        "sha256": forensics.calculate_sha256(path),
        "bytes": os.path.getsize(path) if os.path.isfile(path) else None,
        "media_type": "video" if is_video else ("image" if is_image else
                                               ("audio" if is_audio_only else "unsupported")),
        "visual": None,
        "audio": None,
    }
    if record["media_type"] == "unsupported":
        record["skipped_reason"] = f"Unsupported extension {extension}."
        return record

    workspace = tempfile.mkdtemp(prefix="deeptrace_rob_")
    source_has_audio = has_audio(path) if (is_video or is_audio_only) else False
    record["has_audio_stream"] = source_has_audio
    try:
        # ---- visual ----------------------------------------------------------
        if is_video or is_image:
            base = score_visual(path, frames)
            if not base["ok"]:
                record["visual"] = {"status": "unavailable", "reason": base["reason"]}
            else:
                singles = VIDEO_TRANSFORMS if is_video else IMAGE_TRANSFORMS
                chains = VIDEO_CHAINS if is_video else IMAGE_CHAINS
                by_key = {item["key"]: item for item in singles}
                suffix = ".mp4" if is_video else ".jpg"
                results = []

                for transform in singles:
                    dest = os.path.join(workspace, f"{transform['key']}{transform.get('suffix', suffix)}")
                    print(f"      {transform['key']}", flush=True)
                    ok, reason = run_ffmpeg(path, dest, visual_args(transform, source_has_audio))
                    results.append(_visual_row(transform, dest if ok else None, reason,
                                               base["score"], frames, threshold))

                for chain in chains:
                    steps = [by_key[name] for name in chain["steps"] if name in by_key]
                    if len(steps) != len(chain["steps"]):
                        continue
                    print(f"      {chain['key']}", flush=True)
                    produced, reason = apply_chain(path, workspace, steps, chain["key"],
                                                   steps[-1].get("suffix", suffix), source_has_audio)
                    results.append(_visual_row(chain, produced, reason, base["score"],
                                               frames, threshold))

                record["visual"] = {
                    "status": "completed",
                    "model": deepfake.active_model_name(),
                    "threshold": threshold,
                    "baseline_score": round(base["score"], 4),
                    "baseline_margin": round(abs(base["score"] - threshold), 4),
                    "baseline_near_threshold": abs(base["score"] - threshold) < NEAR_THRESHOLD,
                    "baseline_face_detected": base["face_detected"],
                    "baseline_frames_scored": base["frames_scored"],
                    "transforms": results,
                }

        # ---- audio -----------------------------------------------------------
        if include_audio and (is_audio_only or (is_video and source_has_audio)):
            base_audio = score_audio(path)
            if not base_audio["ok"]:
                record["audio"] = {"status": "unavailable", "reason": base_audio["reason"]}
            else:
                results = []
                for transform in AUDIO_TRANSFORMS:
                    dest = os.path.join(workspace, f"audio_{transform['key']}{transform['suffix']}")
                    print(f"      audio:{transform['key']}", flush=True)
                    tail = (["-vn"] if is_video else []) + transform["args"]
                    ok, reason = run_ffmpeg(path, dest, tail)
                    row = {"key": transform["key"], "label": transform["label"],
                           "stands_for": transform["stands_for"], "family": transform["family"]}
                    if not ok:
                        row.update({"status": "unavailable", "reason": reason})
                    else:
                        scored = score_audio(dest)
                        if not scored["ok"]:
                            row.update({"status": "unavailable", "reason": scored["reason"]})
                        else:
                            row.update({"status": "completed",
                                        "output_bytes": os.path.getsize(dest),
                                        **comparison(base_audio["score"], scored["score"], threshold),
                                        "degraded_rolloff85_hz": scored.get("mean_rolloff85_hz"),
                                        "degraded_discontinuities_per_minute":
                                            scored.get("discontinuities_per_minute")})
                    results.append(row)
                duration = base_audio.get("duration_seconds")
                record["audio"] = {
                    "status": "completed",
                    "model": base_audio.get("method"),
                    "threshold": threshold,
                    "measured_quantity": "editing_indicator (0-1 signal-level editing/processing "
                                         "indicator; not a synthetic-speech score)",
                    "baseline_score": round(base_audio["score"], 4),
                    "baseline_margin": round(abs(base_audio["score"] - threshold), 4),
                    "baseline_duration_seconds": duration,
                    "baseline_rolloff85_hz": base_audio.get("mean_rolloff85_hz"),
                    "baseline_discontinuities_per_minute": base_audio.get("discontinuities_per_minute"),
                    "short_clip_warning": (
                        f"This track is {duration:.2f} s. The indicator's discontinuity term is a "
                        "per-minute rate extrapolated from the clip, so on a track this short a "
                        "single transition saturates that term. Read the deltas below as a property "
                        "of short-clip behaviour as much as of the transform."
                        if duration is not None and duration < SHORT_AUDIO_SECONDS else None),
                    "transforms": results,
                }
        elif include_audio and is_video:
            record["audio"] = {"status": "not_applicable",
                               "reason": "The file carries no audio stream."}
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    return record


def _visual_row(transform: dict, produced: str | None, reason: str | None,
                baseline: float, frames: int, threshold: float) -> dict:
    row = {"key": transform["key"], "label": transform["label"],
           "stands_for": transform["stands_for"], "family": transform["family"]}
    if produced is None:
        row.update({"status": "unavailable", "reason": reason})
        return row
    scored = score_visual(produced, frames)
    if not scored["ok"]:
        row.update({"status": "unavailable", "reason": scored["reason"]})
        return row
    row.update({
        "status": "completed",
        "output_bytes": os.path.getsize(produced),
        **comparison(baseline, scored["score"], threshold),
        "degraded_face_detected": scored["face_detected"],
        "degraded_frames_scored": scored["frames_scored"],
    })
    return row


# --------------------------------------------------------------------------- #
# aggregation
# --------------------------------------------------------------------------- #

def aggregate(records: list[dict], channel: str) -> list[dict]:
    """Per-transform summary across every file that produced a paired result.

    Bucketed by ``(media_type, transform)`` rather than transform alone. Images
    and videos share several transform keys — ``messaging_reupload`` exists for
    both — and merging them would average a JPEG recompression together with an
    H.264 transcode under one label, which are not the same measurement.
    """
    buckets: dict[tuple[str, str], dict] = {}
    for record in records:
        block = record.get(channel)
        if not block or block.get("status") != "completed":
            continue
        media_type = record.get("media_type") or "unknown"
        for row in block.get("transforms", []):
            bucket = buckets.setdefault((media_type, row["key"]), {
                "key": row["key"], "label": row["label"], "stands_for": row["stands_for"],
                "family": row["family"], "media_type": media_type, "deltas": [], "signed": [],
                "preserved": 0, "compared": 0, "failed": 0, "failures": [],
                "flag_gained": 0, "flag_lost": 0, "near_threshold": 0,
                "flips_away_from_threshold": 0,
            })
            if row.get("status") != "completed":
                bucket["failed"] += 1
                if row.get("reason") and len(bucket["failures"]) < 3:
                    bucket["failures"].append({"file": record["file"], "reason": row["reason"]})
                continue
            bucket["compared"] += 1
            bucket["deltas"].append(row["absolute_delta"])
            bucket["signed"].append(row["delta"])
            if row.get("baseline_near_threshold"):
                bucket["near_threshold"] += 1
            if row["decision_preserved"]:
                bucket["preserved"] += 1
            else:
                if not row.get("baseline_near_threshold"):
                    bucket["flips_away_from_threshold"] += 1
                if row["decision_change"] == "cleared_to_flagged":
                    bucket["flag_gained"] += 1
                else:
                    bucket["flag_lost"] += 1

    summaries = []
    for bucket in buckets.values():
        compared = bucket["compared"]
        deltas, signed = bucket["deltas"], bucket["signed"]
        mean_signed = sum(signed) / compared if compared else None
        clear_cut = compared - bucket["near_threshold"]
        clear_preserved = clear_cut - bucket["flips_away_from_threshold"]
        summaries.append({
            "key": bucket["key"], "label": bucket["label"],
            "media_type": bucket["media_type"],
            "stands_for": bucket["stands_for"], "family": bucket["family"],
            "files_compared": compared,
            "files_failed": bucket["failed"],
            "failure_examples": bucket["failures"],
            "mean_absolute_delta": round(sum(deltas) / compared, 4) if compared else None,
            "max_absolute_delta": round(max(deltas), 4) if deltas else None,
            "mean_signed_delta": round(mean_signed, 4) if mean_signed is not None else None,
            "signed_delta_direction": (None if mean_signed is None else
                                       "raises the score" if mean_signed > 0.005 else
                                       "lowers the score" if mean_signed < -0.005 else
                                       "no consistent direction"),
            "decisions_preserved": bucket["preserved"],
            "decision_agreement": round(bucket["preserved"] / compared, 4) if compared else None,
            "became_flagged": bucket["flag_gained"],
            "became_cleared": bucket["flag_lost"],
            # The same figure restricted to files whose original score was not
            # already sitting on the threshold, which is where a flip is
            # attributable to the degradation rather than to the case.
            "borderline_baselines": bucket["near_threshold"],
            "clear_cut_compared": clear_cut,
            "clear_cut_agreement": round(clear_preserved / clear_cut, 4) if clear_cut else None,
        })
    summaries.sort(key=lambda item: (-(item["mean_absolute_delta"] or 0.0),
                                     item["media_type"], item["key"]))
    return summaries


def overall(summaries: list[dict]) -> dict | None:
    compared = sum(item["files_compared"] for item in summaries)
    if not compared:
        return None
    preserved = sum(item["decisions_preserved"] for item in summaries)
    borderline = sum(item["borderline_baselines"] for item in summaries)
    clear_cut = sum(item["clear_cut_compared"] for item in summaries)
    clear_preserved = sum(round((item["clear_cut_agreement"] or 0.0) * item["clear_cut_compared"])
                          for item in summaries)
    weighted = sum((item["mean_absolute_delta"] or 0.0) * item["files_compared"] for item in summaries)
    worst = max(summaries, key=lambda item: item["mean_absolute_delta"] or 0.0)
    return {
        "paired_comparisons": compared,
        "decisions_preserved": preserved,
        "decision_agreement": round(preserved / compared, 4),
        "decision_agreement_95_ci": wilson(preserved, compared),
        "borderline_baselines": borderline,
        "clear_cut_comparisons": clear_cut,
        "clear_cut_agreement": round(clear_preserved / clear_cut, 4) if clear_cut else None,
        "clear_cut_agreement_95_ci": wilson(clear_preserved, clear_cut) if clear_cut else None,
        "mean_absolute_delta": round(weighted / compared, 4),
        "most_disruptive_transform": {"key": worst["key"], "media_type": worst["media_type"],
                                      "label": worst["label"],
                                      "mean_absolute_delta": worst["mean_absolute_delta"],
                                      "decision_agreement": worst["decision_agreement"]},
    }


def wilson(successes: int, total: int, z: float = 1.96):
    if total == 0:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z / denominator * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return [round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4)]


# --------------------------------------------------------------------------- #
# source discovery
# --------------------------------------------------------------------------- #

def discover(explicit: list[str], limit: int) -> tuple[list[str], str]:
    if explicit:
        resolved = []
        for item in explicit:
            path = item if os.path.isabs(item) else os.path.join(REPO_ROOT, item)
            if os.path.isfile(path):
                resolved.append(os.path.abspath(path))
            else:
                print(f"  ignored (not a file): {item}", flush=True)
        return resolved[:limit], "explicit --media arguments"

    supported = IMAGE_EXT | VIDEO_EXT | AUDIO_EXT
    # data/benchmark/dataset/ is deliberately absent from this chain even though it
    # is full of media: it holds the generated accuracy set, which is derived and
    # already re-encoded, and it contains no standalone audio — defaulting to it
    # would silently drop the audio channel and make the artifact depend on
    # whether make_eval_set.py had been run. Pass --media to target it explicitly.
    for directory, description in (
        (SOURCE_DIR, "data/benchmark/robustness_source/"),
        (os.path.join(REPO_ROOT, "data", "demo"), "data/demo/ (the repository's demo inputs)"),
    ):
        if not os.path.isdir(directory):
            continue
        found = []
        for root, dirs, names in os.walk(directory):
            dirs.sort()
            for name in sorted(names):
                if os.path.splitext(name)[1].lower() in supported:
                    found.append(os.path.join(root, name))
        if found:
            extra = os.path.join(REPO_ROOT, "data", "test_video.mp4")
            if description.startswith("data/demo") and os.path.isfile(extra):
                found.append(extra)
            return sorted(found)[:limit], description
    return [], "no source directory contained media"


def source_fingerprint(files: list[str]) -> str:
    digest = hashlib.sha256()
    for path in files:
        digest.update(os.path.basename(path).encode("utf-8"))
        digest.update((forensics.calculate_sha256(path) or "").encode("utf-8"))
    return digest.hexdigest()[:16]


# --------------------------------------------------------------------------- #

def caveats(records: list[dict], source_description: str, model: str) -> list[str]:
    notes = [
        "Every figure here is a paired comparison: the same file, scored before and after a real "
        "ffmpeg transform. No labels are involved, so nothing here is an accuracy measurement — "
        "it measures stability under degradation, not correctness.",
        "Decision agreement is measured against DeepTrace's own baseline score for the original "
        "file. If that baseline is wrong, a preserved decision means the same wrong answer "
        "survived the transform. Read this together with the labelled metrics, not instead of them.",
        "The transforms reproduce what a transcoder does — resolution, frame rate, codec, bitrate, "
        "metadata stripping and letterboxing. They do not reproduce monitor moire, camera-on-screen "
        "capture, capture-card colour handling, or a specific platform's proprietary encoder ladder.",
        f"Source media: {source_description}. Robustness is a property of the pair (detector, "
        "media), so these numbers describe these files and do not transfer to a different corpus.",
        "A transform that shifts every score by a similar amount can leave decision agreement at "
        "100% while still having moved the case away from its true score. The mean signed delta is "
        "reported so that systematic drift is visible rather than hidden by the agreement figure.",
        f"Files whose original score sat within {NEAR_THRESHOLD} of the threshold are counted "
        "separately as 'borderline'. A borderline file flips under almost any transform, so "
        "including it in the headline agreement figure would blame the degradation for what is "
        "really an undecided case. Both figures are published: decision_agreement over everything, "
        "and clear_cut_agreement over the files that were not borderline.",
    ]
    if "fallback" in model.lower():
        notes.insert(0,
            "The Xception deepfakebench weights were not loaded, so the visual scores came from the "
            f"deterministic image-statistics fallback ('{model}'). A residual- and compression-based "
            "heuristic is expected to be highly sensitive to re-encoding, so these deltas describe "
            "the fallback's fragility, not the learned detector's. Install the weights and re-run.")

    short_tracks = [record["file"] for record in records
                    if (record.get("audio") or {}).get("short_clip_warning")]
    if short_tracks:
        notes.append(
            "The audio editing indicator derives a per-minute discontinuity rate, so on tracks "
            f"shorter than {SHORT_AUDIO_SECONDS:.0f} s a single loudness transition saturates that "
            f"term. That applies to: {', '.join(short_tracks)}. Their audio deltas partly measure "
            "short-clip extrapolation rather than the transform.")

    silent = [record["file"] for record in records
              if record.get("media_type") == "video" and record.get("has_audio_stream") is False]
    if silent:
        notes.append(
            f"No audio robustness figure exists for {', '.join(silent)}: the file carries no audio "
            "stream. That is reported as not_applicable rather than as a passing result.")

    if len(records) < 5:
        notes.append(
            f"Only {len(records)} source file(s) were evaluated. Per-transform agreement figures at "
            "this sample size have very wide intervals; the reported 95% Wilson interval on the "
            "overall figure quantifies that, and the per-transform counts are given so they are not "
            "read as percentages of a large sample.")
    return notes


def main() -> int:
    default_frames = 8
    try:
        default_frames = max(1, int(os.environ.get("DEEPTRACE_FRAME_SAMPLES", "") or 8))
    except ValueError:
        pass

    parser = argparse.ArgumentParser(
        description="Measure DeepTrace's score stability under compression, re-upload and "
                    "screen-recording degradation.")
    parser.add_argument("--media", action="append", default=[],
                        help="A file to evaluate. Repeatable. Overrides source discovery.")
    parser.add_argument("--frames", type=int, default=default_frames,
                        help=f"Frames sampled per video, per variant (default {default_frames}).")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"Decision threshold for the agreement figure (default {DEFAULT_THRESHOLD}).")
    parser.add_argument("--max-files", type=int, default=8,
                        help="Cap on discovered files, so a large folder does not run for hours.")
    parser.add_argument("--skip-audio", action="store_true",
                        help="Visual transforms only.")
    args = parser.parse_args()

    print("DeepTrace robustness evaluation")

    capability = forensics.ffmpeg_capability_detail()
    if not capability["available"]:
        print("\n  ffmpeg and ffprobe are both required to build degraded copies.")
        print(f"    ffmpeg:  {capability['ffmpeg']['detail']}")
        print(f"    ffprobe: {capability['ffprobe']['detail']}")
        print("\n  Nothing was written. GET /api/benchmark keeps reporting robustness as "
              "unavailable rather than showing a partial result.")
        return NO_FFMPEG_EXIT

    files, source_description = discover(args.media, max(1, args.max_files))
    if not files:
        print(f"\n  No source media found ({source_description}).")
        print(f"  Drop authentic media into {SOURCE_DIR} or pass --media <path>, then re-run.")
        return NOTHING_TO_EVALUATE_EXIT

    print(f"  source:    {source_description}")
    print(f"  files:     {len(files)}")
    print(f"  frames:    {args.frames} per video variant")
    print(f"  threshold: {args.threshold}")

    started = time.time()
    records = []
    for index, path in enumerate(files, 1):
        print(f"\n  [{index}/{len(files)}] {os.path.basename(path)}", flush=True)
        records.append(evaluate_file(path, max(1, args.frames), args.threshold, not args.skip_audio))

    model = deepfake.active_model_name()
    visual_summary = aggregate(records, "visual")
    audio_summary = aggregate(records, "audio")

    payload = {
        "generated_at_utc": forensics.utc_now_iso(),
        "duration_seconds": round(time.time() - started, 1),
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "manipulation_model": model,
            "ffmpeg": capability["ffmpeg"]["detail"],
            "frames_per_video": max(1, args.frames),
        },
        "threshold": args.threshold,
        "source": {
            "description": source_description,
            "file_count": len(files),
            "fingerprint": source_fingerprint(files),
        },
        "what_this_measures": (
            "Score stability, not accuracy. Each source file is scored by the real pipeline, then "
            "re-scored after a real ffmpeg transform that stands for a specific real-world event "
            "(platform recompression, a messaging re-upload, a screen recording). The headline "
            "figure is decision agreement: the share of paired comparisons where the degraded copy "
            "lands on the same side of the threshold as the original."
        ),
        "visual": {
            "channel": "Image/video manipulation signal",
            "per_transform": visual_summary,
            "overall": overall(visual_summary),
        },
        "audio": {
            "channel": "Audio editing indicator (deterministic signal analysis, no ML model)",
            "per_transform": audio_summary,
            "overall": overall(audio_summary),
        },
        "per_file": records,
        "caveats": caveats(records, source_description, model),
        "provenance": (
            "Produced by scripts/robustness.py. Every degraded copy was generated on this machine "
            "by ffmpeg and re-scored by the same services the API uses. No delta, agreement figure "
            "or transform result is estimated or carried over from another run."
        ),
    }

    os.makedirs(BENCHMARK_DIR, exist_ok=True)
    with open(ROBUSTNESS_JSON, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    print(f"\nWrote {ROBUSTNESS_JSON}")
    for channel in ("visual", "audio"):
        block = payload[channel]["overall"]
        if not block:
            print(f"  {channel}: no paired comparison completed.")
            continue
        print(f"  {channel}: decision agreement {block['decision_agreement']} "
              f"(95% CI {block['decision_agreement_95_ci']}) over {block['paired_comparisons']} "
              f"pairs, mean |delta| {block['mean_absolute_delta']}, worst "
              f"'{block['most_disruptive_transform']['key']}'")
        if block["borderline_baselines"]:
            print(f"    of which {block['borderline_baselines']} had a borderline baseline; "
                  f"agreement over the {block['clear_cut_comparisons']} clear-cut pairs was "
                  f"{block['clear_cut_agreement']}")
    for row in visual_summary + audio_summary:
        print(f"    {row['media_type']:<6} {row['key']:<30} |delta| {row['mean_absolute_delta']}  "
              f"agreement {row['decision_agreement']}  n={row['files_compared']}"
              + (f"  failed={row['files_failed']}" if row["files_failed"] else ""))
    deepfake.release_models()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
