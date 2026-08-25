"""Audio stream forensics.

Measures container/codec facts and signal-level statistics that are useful when
assessing whether an audio track has been edited, spliced or re-encoded.

Deliberate scope limit: nothing here claims to detect AI-generated or cloned
speech. Those claims need a trained synthetic-speech classifier, which this
prototype does not ship. Speaker comparison lives in ``services/voice.py``.
"""

import os
import subprocess

import numpy as np

from services.forensics import _binary, load_audio_samples, probe_media, summarize_probe


def has_audio_stream(file_path: str) -> bool | None:
    """True/False from ffprobe, or None when ffprobe could not run."""
    probe = probe_media(file_path)
    if probe is None:
        return None
    return any((s.get("codec_type") == "audio") for s in (probe.get("streams") or []))


def extract_audio_track(media_path: str, dest_path: str) -> tuple[bool, str | None]:
    """Decode the audio stream to 16 kHz mono PCM WAV.

    16 kHz mono is what the ECAPA speaker model expects, and it keeps the
    preserved audio artifact small enough to hash and store per case.
    """
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    try:
        subprocess.run(
            [
                _binary("ffmpeg"), "-y", "-i", media_path,
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                dest_path,
            ],
            check=True,
            capture_output=True,
            timeout=180,
            shell=False,
        )
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        reason = detail[-1] if detail else "ffmpeg returned a non-zero exit status"
        return False, reason[:300]
    except FileNotFoundError:
        return False, "FFmpeg is not installed or not on PATH."
    except subprocess.TimeoutExpired:
        return False, "Audio extraction timed out after 180 s."
    except Exception as error:
        return False, str(error)[:300]

    if not os.path.isfile(dest_path) or os.path.getsize(dest_path) == 0:
        try:
            os.remove(dest_path)
        except OSError:
            pass
        return False, "No decodable audio stream was found in the file."
    return True, None


def _spectral_stats(chunk: np.ndarray, sample_rate: int) -> tuple[float, float]:
    """Spectral centroid (Hz) and 85 % roll-off frequency (Hz) for one window."""
    spectrum = np.abs(np.fft.rfft(chunk))
    total = float(spectrum.sum())
    freqs = np.fft.rfftfreq(len(chunk), d=1.0 / sample_rate)
    if total <= 0:
        return 0.0, 0.0
    centroid = float((spectrum * freqs).sum() / total)
    cumulative = np.cumsum(spectrum)
    rolloff_idx = int(np.searchsorted(cumulative, 0.85 * total))
    rolloff = float(freqs[min(rolloff_idx, len(freqs) - 1)])
    return centroid, rolloff


def analyze_audio(audio_path: str, source_probe: dict | None = None) -> dict:
    """Container facts plus signal statistics and splice indicators."""
    if not audio_path or not os.path.isfile(audio_path):
        return {
            "status": "unavailable",
            "reason": "No decoded audio track was available for analysis.",
            "method": "Container probe + PCM signal statistics",
        }

    samples, sample_rate = load_audio_samples(audio_path)
    if samples is None or not sample_rate:
        return {
            "status": "unavailable",
            "reason": "The decoded audio track could not be read as PCM samples.",
            "method": "Container probe + PCM signal statistics",
        }

    container = summarize_probe(source_probe) if source_probe else {}
    duration = len(samples) / float(sample_rate)

    peak = float(np.max(np.abs(samples)))
    rms = float(np.sqrt(np.mean(samples ** 2)))
    # Samples within ~0.2 % of full scale are treated as clipped.
    clipped = int(np.count_nonzero(np.abs(samples) >= 0.998))
    clipping_ratio = clipped / float(samples.size)
    dc_offset = float(np.mean(samples))

    window = max(int(0.05 * sample_rate), 128)          # 50 ms analysis windows
    n_windows = max(1, len(samples) // window)
    frame_rms: list[float] = []
    centroids: list[float] = []
    rolloffs: list[float] = []
    for i in range(n_windows):
        chunk = samples[i * window:(i + 1) * window]
        if chunk.size < 32:
            continue
        frame_rms.append(float(np.sqrt(np.mean(chunk ** 2))))
        centroid, rolloff = _spectral_stats(chunk, sample_rate)
        centroids.append(centroid)
        rolloffs.append(rolloff)

    rms_arr = np.array(frame_rms, dtype=np.float32)
    silence_threshold = max(1e-4, float(rms) * 0.1)
    silence_ratio = float(np.count_nonzero(rms_arr < silence_threshold) / max(rms_arr.size, 1))

    peak_db = 20 * np.log10(peak) if peak > 0 else -120.0
    rms_db = 20 * np.log10(rms) if rms > 0 else -120.0
    crest_factor_db = float(peak_db - rms_db)

    # Splice indicators: windows where loudness jumps far outside the track's own
    # normal variation. A robust (median absolute deviation) threshold is used so
    # a few loud moments do not raise the bar for the whole file.
    discontinuities: list[dict] = []
    if rms_arr.size >= 8:
        deltas = np.abs(np.diff(rms_arr))
        median_delta = float(np.median(deltas))
        mad = float(np.median(np.abs(deltas - median_delta))) or 1e-6
        threshold = median_delta + 6.0 * mad
        for idx in np.argsort(deltas)[::-1]:
            if deltas[idx] <= threshold or len(discontinuities) >= 12:
                break
            discontinuities.append({
                "timestamp_seconds": round(float((idx + 1) * window) / sample_rate, 3),
                "rms_delta": round(float(deltas[idx]), 5),
                "threshold": round(threshold, 5),
            })
        discontinuities.sort(key=lambda item: item["timestamp_seconds"])

    discontinuity_rate = len(discontinuities) / max(duration / 60.0, 1e-6)

    observations: list[str] = []
    if container.get("audio_codec"):
        channels = container.get("audio_channels")
        observations.append(
            f"Audio stream is {container['audio_codec']} at "
            f"{container.get('audio_sample_rate', sample_rate)} Hz"
            + (f", {channels} channel(s)." if channels else ".")
        )
    if clipping_ratio > 0.005:
        observations.append(
            f"{clipping_ratio * 100:.2f}% of samples sit at full scale, indicating clipping — "
            "typical of loudness-maximised or re-recorded audio."
        )
    if silence_ratio > 0.5:
        observations.append(
            f"{silence_ratio * 100:.0f}% of analysis windows are near-silent; "
            "speech content is sparse in this track."
        )
    if discontinuities:
        first = ", ".join(f"{d['timestamp_seconds']:.2f}s" for d in discontinuities[:5])
        observations.append(
            f"{len(discontinuities)} abrupt loudness transition(s) detected (at {first}). "
            "Transitions of this kind occur at edit points, but also at natural cuts and scene changes."
        )
    else:
        observations.append("No abrupt loudness transitions were detected above the robust threshold.")
    if abs(dc_offset) > 0.01:
        observations.append(
            f"A DC offset of {dc_offset:+.4f} is present, which usually points to a capture-chain issue."
        )
    if centroids:
        observations.append(
            f"Mean spectral centroid is {float(np.mean(centroids)):.0f} Hz with 85% roll-off at "
            f"{float(np.mean(rolloffs)):.0f} Hz."
        )
    if container.get("audio_sample_rate") and rolloffs:
        nyquist = container["audio_sample_rate"] / 2.0
        mean_rolloff = float(np.mean(rolloffs))
        if nyquist > 8000 and mean_rolloff < nyquist * 0.35:
            observations.append(
                f"Energy rolls off well below the Nyquist limit ({nyquist:.0f} Hz), which is consistent "
                "with the track having been encoded at a lower bandwidth before this one."
            )

    # Bounded 0-1 indicator used as a low-weight input to risk fusion. It measures
    # editing/processing artefacts only — never synthesis.
    editing_indicator = float(np.clip(
        min(discontinuity_rate / 20.0, 1.0) * 0.6 + min(clipping_ratio / 0.02, 1.0) * 0.4,
        0.0, 1.0,
    ))

    return {
        "status": "completed",
        "method": "Container probe + PCM signal statistics",
        "model_status": "Deterministic signal analysis (no ML model involved)",
        "analyzed_file": os.path.basename(audio_path),
        "decoded_sample_rate": sample_rate,
        "decoded_duration_seconds": round(duration, 3),
        "container": {
            "codec": container.get("audio_codec"),
            "sample_rate": container.get("audio_sample_rate"),
            "channels": container.get("audio_channels"),
            "bitrate_bps": container.get("audio_bitrate_bps"),
            "stream_duration_seconds": container.get("audio_duration_seconds"),
        },
        "levels": {
            "peak": round(peak, 6),
            "peak_dbfs": round(float(peak_db), 2),
            "rms": round(rms, 6),
            "rms_dbfs": round(float(rms_db), 2),
            "crest_factor_db": round(crest_factor_db, 2),
            "dc_offset": round(dc_offset, 6),
            "clipped_samples": clipped,
            "clipping_ratio": round(clipping_ratio, 6),
            "silence_ratio": round(silence_ratio, 4),
        },
        "spectral": {
            "windows_analyzed": len(centroids),
            "window_ms": round(window * 1000.0 / sample_rate, 1),
            "mean_centroid_hz": round(float(np.mean(centroids)), 1) if centroids else None,
            "mean_rolloff85_hz": round(float(np.mean(rolloffs)), 1) if rolloffs else None,
            "centroid_std_hz": round(float(np.std(centroids)), 1) if centroids else None,
        },
        "discontinuities": discontinuities,
        "discontinuity_count": len(discontinuities),
        "discontinuities_per_minute": round(discontinuity_rate, 2),
        "editing_indicator": round(editing_indicator, 4),
        "observations": observations,
        "interpretation": (
            "These are signal-level editing and re-encoding indicators. DeepTrace does not "
            "include a synthetic-speech classifier, so this module makes no claim about whether "
            "the audio was AI-generated. Speaker comparison against an enrolled reference is "
            "reported separately under Voice."
        ),
    }
