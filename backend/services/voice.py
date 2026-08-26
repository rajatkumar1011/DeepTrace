"""Speaker comparison against an enrolled reference voice.

Primary model: SpeechBrain ECAPA-TDNN (``speechbrain/spkrec-ecapa-voxceleb``),
which produces a cosine similarity between two utterances plus a same/different
speaker decision at the model's own threshold.

This module answers "does this voice match the enrolled person?" — it does not
answer "was this voice synthesised?". DeepTrace ships no synthetic-speech
classifier, and the payload says so rather than implying the capability.

Two things are deliberately refused rather than approximated:

* If ECAPA cannot be loaded, this module reports **unavailable**. There is a
  deterministic spectral summary in here, and it is genuinely useful for
  enrollment bookkeeping, but a spectral summary is not a speaker embedding. Were
  its cosine published as ``voice_match_score`` the risk engine would fuse it as
  "cosine similarity of speaker embeddings" against ECAPA's own threshold, and
  the report would print it beside a real one. The number is kept, under a name
  nothing fuses, and the status says plainly that no speaker comparison happened.
* If the audio is shorter than a speaker model can work with, the score is
  reported together with the measurement that undermines it, and the verdict is
  inconclusive. A 0.4-second clip yields a confident-looking cosine; the duration
  is the reason not to trust it, so it travels with the score.
"""

import os

import numpy as np

# ECAPA-VoxCeleb's published decision threshold for the verification task.
ECAPA_THRESHOLD = 0.25

# DeepTrace's own floor, not a published model specification. VoxCeleb test
# segments are seconds long; below roughly a second there is not enough voiced
# speech for a speaker embedding to mean much, and the score becomes a function
# of the noise floor. Scores below this are reported with the duration and marked
# inconclusive rather than withheld — an investigator should see both.
MIN_RELIABLE_AUDIO_SECONDS = 1.0
# Below this the comparison is refused outright: there is no utterance to embed.
MIN_USABLE_AUDIO_SECONDS = 0.25

_speaker_model = None
_speaker_model_error = None


def get_speaker_model():
    global _speaker_model, _speaker_model_error
    if _speaker_model is None and _speaker_model_error is None:
        try:
            import torch
            from speechbrain.inference.speaker import SpeakerRecognition
            from speechbrain.utils.fetching import LocalStrategy

            device = "cuda" if torch.cuda.is_available() else "cpu"
            model_dir = os.path.abspath(os.path.join(
                os.path.dirname(__file__), "..", "pretrained_models", "spkrec-ecapa-voxceleb"
            ))
            _speaker_model = SpeakerRecognition.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb",
                savedir=model_dir,
                run_opts={"device": device},
                # COPY avoids symlink creation, which needs elevated privileges on Windows.
                local_strategy=LocalStrategy.COPY,
            )
        except Exception as error:
            print(f"Heavy speaker model unavailable, using lightweight fallback: {error}")
            _speaker_model_error = str(error)[:300]
            _speaker_model = None
    return _speaker_model


def extract_audio(video_path: str, output_audio_path: str) -> bool:
    """Kept for callers that only need a boolean; FFmpeg handling lives in services.audio."""
    from services.audio import extract_audio_track

    ok, _ = extract_audio_track(video_path, output_audio_path)
    return ok


def _fallback_audio_embedding(audio_path: str):
    """Deterministic spectral summary. Not a speaker model — clearly labelled by callers."""
    from services.forensics import load_audio_samples

    samples, _ = load_audio_samples(audio_path)
    if samples is None or samples.size == 0:
        return None
    samples = samples / (float(np.max(np.abs(samples))) or 1.0)
    window = max(1, len(samples) // 64)
    features: list[float] = []
    for start in range(0, len(samples), window):
        chunk = samples[start:start + window]
        if chunk.size == 0:
            continue
        features.extend([
            float(np.mean(chunk)),
            float(np.std(chunk)),
            float(np.sqrt(np.mean(chunk ** 2))),
        ])
    return np.array(features[:192], dtype=np.float32).tolist() if features else None


def generate_voice_embedding(audio_path: str):
    """Speaker embedding for the reference audio stored at enrollment."""
    model = get_speaker_model()
    try:
        if model is not None:
            import torch
            import torchaudio

            signal, sample_rate = torchaudio.load(audio_path)
            if sample_rate != 16000:
                signal = torchaudio.transforms.Resample(sample_rate, 16000)(signal)
            with torch.no_grad():
                embedding = model.encode_batch(signal)
            return embedding[0][0].cpu().numpy().tolist()
        return _fallback_audio_embedding(audio_path)
    except Exception as error:
        print(f"Error generating voice embedding: {error}")
        return _fallback_audio_embedding(audio_path)


def embedding_model_name() -> str:
    return "speechbrain/spkrec-ecapa-voxceleb" if get_speaker_model() is not None else "Lightweight fallback"


def compare_voice_embeddings(embedding1, embedding2) -> float:
    if not embedding1 or not embedding2:
        return 0.0
    a = np.array(embedding1, dtype=np.float32)
    b = np.array(embedding2, dtype=np.float32)
    if a.shape != b.shape:
        print(f"Voice embedding dimension mismatch {a.shape} vs {b.shape}; returning 0.0")
        return 0.0
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.clip(np.dot(a, b) / denom, -1.0, 1.0)) if denom else 0.0


def audio_duration_seconds(audio_path: str) -> float | None:
    """Decoded duration, or None when the file could not be decoded at all."""
    from services.forensics import load_audio_samples

    samples, sample_rate = load_audio_samples(audio_path)
    if samples is None or not sample_rate or samples.size == 0:
        return None
    return round(float(samples.size) / float(sample_rate), 3)


def compare_voices(reference_audio: str, subject_audio: str) -> dict:
    """Compare two audio files and describe the method actually used.

    On the fallback path ``similarity_score`` is deliberately absent. The
    spectral cosine is returned as ``spectral_summary_cosine`` instead, so that a
    caller reaching for a speaker score finds nothing rather than finding a
    different measurement wearing the same name.
    """
    model = get_speaker_model()
    try:
        if model is not None:
            score, prediction = model.verify_files(
                reference_audio.replace("\\", "/"),
                subject_audio.replace("\\", "/"),
            )
            similarity = float(score.item())
            same_speaker = bool(prediction.item()) if hasattr(prediction, "item") else bool(prediction)
            return {
                "similarity_score": similarity,
                "prediction": same_speaker,
                "decision_threshold": ECAPA_THRESHOLD,
                "method": "ECAPA-TDNN speaker verification",
                "model_status": "Advanced ML model available",
                "model_name": "ECAPA-TDNN / VoxCeleb",
                "model_version": "speechbrain/spkrec-ecapa-voxceleb",
            }

        spectral = compare_voice_embeddings(
            generate_voice_embedding(reference_audio),
            generate_voice_embedding(subject_audio),
        )
        return {
            "similarity_score": None,
            "spectral_summary_cosine": round(float(spectral), 6),
            "prediction": None,
            "decision_threshold": None,
            "method": "Not performed — ECAPA-TDNN could not be loaded",
            "model_status": "Speaker verification model unavailable on this machine",
            "model_name": None,
            "model_version": None,
            "fallback_reason": _speaker_model_error,
            "fallback_note": (
                "A deterministic spectral summary of the two files was computed and agrees at "
                f"{float(spectral):.3f}. That is a comparison of energy envelopes, not of speaker "
                "identity: it responds to recording conditions and loudness, and it is reported "
                "here only so the figure is not mistaken for a speaker match elsewhere."
            ),
        }
    except Exception as error:
        print(f"Error comparing voices: {error}")
        return {
            "similarity_score": None,
            "method": "Unavailable",
            "model_status": "Voice comparison failed",
            "error": str(error)[:300],
        }


def verify_speaker(reference_audio: str | None, subject_audio: str | None,
                   identity_name: str | None = None) -> dict:
    """Full voice-module payload with explicit availability states.

    States are kept distinct on purpose: "no audio in the media", "no reference
    voice enrolled" and "the model failed" are different findings for an
    investigator, and collapsing them into one 'unavailable' would hide why.
    """
    if not subject_audio or not os.path.isfile(subject_audio):
        return {
            "status": "unavailable",
            "voice_match_score": None,
            "reason": "The submitted media contains no decodable audio track, so no voice could be compared.",
            "method": "ECAPA-TDNN speaker verification",
            "excluded_from_risk": True,
        }
    if not reference_audio or not os.path.isfile(reference_audio):
        return {
            "status": "not_applicable",
            "voice_match_score": None,
            "reason": (
                "The submitted media contains audio, but no reference voice sample is enrolled for "
                + (f"{identity_name}. " if identity_name else "this identity. ")
                + "Enroll a reference voice sample to enable speaker comparison."
            ),
            "audio_present": True,
            "method": "ECAPA-TDNN speaker verification",
            "excluded_from_risk": True,
        }

    comparison = compare_voices(reference_audio, subject_audio)
    similarity = comparison.get("similarity_score")
    subject_seconds = audio_duration_seconds(subject_audio)
    reference_seconds = audio_duration_seconds(reference_audio)
    audio_measured = {
        "subject_seconds": subject_seconds,
        "reference_seconds": reference_seconds,
        "reliable_floor_seconds": MIN_RELIABLE_AUDIO_SECONDS,
        "usable_floor_seconds": MIN_USABLE_AUDIO_SECONDS,
        "floor_basis": (
            "DeepTrace's own conservative floor, not a published ECAPA specification. "
            "VoxCeleb evaluation segments are several seconds long."
        ),
    }

    if similarity is None:
        # Includes the case where ECAPA could not be loaded. That is an
        # unavailable module, not a completed one with a substitute number:
        # nothing downstream may fuse or print a speaker score that no speaker
        # model produced.
        return {
            "status": "unavailable",
            "voice_match_score": None,
            "audio_present": True,
            "audio_measured": audio_measured,
            "reason": (
                "Speaker verification could not be completed: "
                f"{comparison.get('error') or comparison.get('model_status')}"
            ),
            **{k: v for k, v in comparison.items() if k not in {"similarity_score", "error"}},
            "excluded_from_risk": True,
        }

    shortest = min([value for value in (subject_seconds, reference_seconds) if value is not None],
                   default=None)
    if shortest is not None and shortest < MIN_USABLE_AUDIO_SECONDS:
        # Too little audio to embed. The model still returns a number; publishing
        # it as a match score would be publishing a measurement of the noise floor.
        return {
            "status": "unavailable",
            "voice_match_score": None,
            "audio_present": True,
            "audio_measured": audio_measured,
            "reason": (
                f"The shorter of the two recordings is {shortest:.2f}s, below the "
                f"{MIN_USABLE_AUDIO_SECONDS:.2f}s minimum DeepTrace requires for a speaker "
                "comparison. A score computed from this little audio would describe the "
                "recording conditions rather than the speaker, so none is reported."
            ),
            "method": comparison.get("method"),
            "model_name": comparison.get("model_name"),
            "model_version": comparison.get("model_version"),
            "excluded_from_risk": True,
        }

    threshold = comparison.get("decision_threshold")
    prediction = comparison.get("prediction")
    if prediction is None and threshold is not None:
        prediction = similarity >= threshold

    short_audio = shortest is not None and shortest < MIN_RELIABLE_AUDIO_SECONDS

    if threshold is None:
        interpretation = (
            "No decision threshold is available for the method that produced this value, so it "
            "cannot be turned into a same-speaker judgement."
        )
        verdict = "inconclusive"
    elif short_audio:
        # The score is real and is reported. What it cannot carry is a verdict:
        # the duration is the reason, and it travels with the number.
        interpretation = (
            f"Speaker similarity {similarity:.3f} was computed, but the shorter recording is only "
            f"{shortest:.2f}s — under the {MIN_RELIABLE_AUDIO_SECONDS:.1f}s DeepTrace treats as the "
            "floor for a dependable speaker comparison. Scores from clips this short move with "
            "recording conditions, so the comparison is inconclusive regardless of which side of "
            f"the {threshold:.2f} threshold the value falls on."
        )
        verdict = "inconclusive"
    elif prediction:
        interpretation = (
            f"Speaker similarity {similarity:.3f} is above the model's {threshold:.2f} decision "
            "threshold, consistent with the same speaker as the enrolled reference."
        )
        verdict = "consistent_with_reference"
    elif similarity >= threshold * 0.6:
        interpretation = (
            f"Speaker similarity {similarity:.3f} sits below the {threshold:.2f} threshold but is not "
            "clearly separated from it. Short or noisy audio produces scores in this band, so the "
            "comparison is inconclusive."
        )
        verdict = "inconclusive"
    else:
        interpretation = (
            f"Speaker similarity {similarity:.3f} is well below the model's {threshold:.2f} threshold, "
            "indicating the voice differs from the enrolled reference."
        )
        verdict = "differs_from_reference"

    return {
        "status": "completed",
        "voice_match_score": round(similarity, 6),
        "audio_present": True,
        "audio_measured": audio_measured,
        "audio_long_enough": not short_audio,
        "same_speaker_prediction": bool(prediction) if prediction is not None else None,
        "verdict": verdict,
        "interpretation": interpretation,
        "identity_name": identity_name,
        "note": (
            "Speaker verification compares this voice to the enrolled reference. It does not "
            "determine whether the audio was synthetically generated."
        ),
        **{k: v for k, v in comparison.items() if k != "similarity_score"},
        # An inconclusive verdict is not a finding the risk score may lean on. The
        # number stays visible in the payload and the report; it just does not get
        # a weight in fusion, and the reason above says why.
        "excluded_from_risk": verdict == "inconclusive",
        "exclusion_reason": (interpretation if verdict == "inconclusive" else None),
    }


def release_models():
    global _speaker_model, _speaker_model_error
    _speaker_model = None
    _speaker_model_error = None
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
