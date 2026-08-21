import os
import numpy as np

_speaker_model = None

def get_speaker_model():
    global _speaker_model
    if _speaker_model is None:
        try:
            import torch
            from speechbrain.inference.speaker import SpeakerRecognition
            from speechbrain.utils.fetching import LocalStrategy

            device = "cuda" if torch.cuda.is_available() else "cpu"
            model_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pretrained_models", "spkrec-ecapa-voxceleb"))
            _speaker_model = SpeakerRecognition.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb", 
                savedir=model_dir,
                run_opts={"device": device},
                local_strategy=LocalStrategy.COPY,
            )
        except Exception as e:
            print(f"Heavy speaker model unavailable, using lightweight fallback: {e}")
            _speaker_model = None
    return _speaker_model

def extract_audio(video_path: str, output_audio_path: str):
    """
    Extracts audio from video using librosa/soundfile or ffmpeg.
    Since we don't have guaranteed ffmpeg on path, we'll try an alternative or rely on torchaudio.
    """
    try:
        import subprocess
        # Use ffmpeg via subprocess. If ffmpeg is missing, this will fail.
        subprocess.run([
            'ffmpeg', '-y', '-i', video_path, 
            '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1', 
            output_audio_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"Error extracting audio: {e}")
        return False

def generate_voice_embedding(audio_path: str):
    """
    Generates a speaker embedding for the given audio file.
    """
    model = get_speaker_model()
    try:
        if model is not None:
            import torch
            import torchaudio

            signal, fs = torchaudio.load(audio_path)
            if fs != 16000:
                resampler = torchaudio.transforms.Resample(fs, 16000)
                signal = resampler(signal)

            with torch.no_grad():
                embedding = model.encode_batch(signal)
            return embedding[0][0].cpu().numpy().tolist()

        return _fallback_audio_embedding(audio_path)
    except Exception as e:
        print(f"Error generating voice embedding: {e}")
        return _fallback_audio_embedding(audio_path)

def _fallback_audio_embedding(audio_path: str):
    try:
        from scipy.io import wavfile
        sample_rate, data = wavfile.read(audio_path)
        if data.ndim > 1:
            data = data.mean(axis=1)
        data = data.astype(np.float32)
        if data.size == 0:
            return None

        data = data / (np.max(np.abs(data)) or 1.0)
        window = max(1, len(data) // 64)
        features = []
        for i in range(0, len(data), window):
            chunk = data[i:i + window]
            features.extend([
                float(np.mean(chunk)),
                float(np.std(chunk)),
                float(np.sqrt(np.mean(chunk ** 2))),
            ])
        return np.array(features[:192], dtype=np.float32).tolist()
    except Exception as e:
        print(f"Fallback voice embedding unavailable: {e}")
        return None

def compare_voices(audio_path1: str, audio_path2: str) -> float:
    """
    Compare two audio files and return a similarity score (-1 to 1).
    """
    model = get_speaker_model()
    try:
        if model is not None:
            score, prediction = model.verify_files(
                audio_path1.replace("\\", "/"),
                audio_path2.replace("\\", "/"),
            )
            return float(score.item())

        emb1 = generate_voice_embedding(audio_path1)
        emb2 = generate_voice_embedding(audio_path2)
        return compare_voice_embeddings(emb1, emb2)
    except Exception as e:
        print(f"Error comparing voices: {e}")
        return 0.0

def compare_voice_embeddings(embedding1, embedding2) -> float:
    import numpy as np
    if not embedding1 or not embedding2:
        return 0.0
    emb1 = np.array(embedding1)
    emb2 = np.array(embedding2)
    
    # Cosine similarity
    dot_product = np.dot(emb1, emb2)
    norm1 = np.linalg.norm(emb1)
    norm2 = np.linalg.norm(emb2)
    
    if norm1 == 0 or norm2 == 0:
        return 0.0
        
    similarity = dot_product / (norm1 * norm2)
    return float(similarity)

def release_models():
    global _speaker_model
    _speaker_model = None
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
