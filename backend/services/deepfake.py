import os

from PIL import Image
import cv2
import numpy as np
from datetime import datetime

_processor = None
_model = None
_model_name = None

_DEEPFAKEBENCH_WEIGHTS = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "pretrained_models", "deepfakebench", "xception_best.pth"
))

def _load_deepfakebench_xception():
    """Load DeepfakeBench's released Xception checkpoint when installed locally."""
    if not os.path.isfile(_DEEPFAKEBENCH_WEIGHTS):
        return None

    import torch
    from services.deepfakebench_xception import Xception

    device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
    checkpoint = torch.load(_DEEPFAKEBENCH_WEIGHTS, map_location=device)
    state_dict = checkpoint.get("state_dict", checkpoint)
    state_dict = {
        key.removeprefix("backbone."): value for key, value in state_dict.items()
    }
    model = Xception()
    model.load_state_dict(state_dict, strict=True)
    return model.eval().to(device)

def get_deepfake_model():
    global _processor, _model, _model_name
    if _model is None:
        try:
            import torch
            deepfakebench_model = _load_deepfakebench_xception()
            if deepfakebench_model is not None:
                _model = deepfakebench_model
                _processor = "deepfakebench"
                _model_name = "DeepfakeBench Xception"
                return _processor, _model

            from transformers import ViTForImageClassification, ViTImageProcessor

            device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
            model_name = "Hemg/Deepfake-Detection"
            _processor = ViTImageProcessor.from_pretrained(model_name)
            _model = ViTForImageClassification.from_pretrained(model_name).eval().to(device)
            _model_name = model_name
        except Exception as e:
            print(f"Heavy deepfake model unavailable, using heuristic fallback: {e}")
            _processor = None
            _model = None
            _model_name = None
    return _processor, _model

def _heuristic_fake_probability(image_path: str) -> dict:
    img = cv2.imread(image_path)
    if img is None:
        return None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
    brightness = float(np.mean(gray)) / 255.0
    contrast = float(np.std(gray)) / 128.0

    # Lower sharpness and unusual brightness/contrast patterns are treated as more suspicious.
    sharpness_component = max(0.0, min(1.0, 1.0 - (blur_score / 400.0)))
    brightness_component = abs(brightness - 0.5)
    contrast_component = max(0.0, 1.0 - contrast)
    fake_probability = max(0.0, min(1.0, (sharpness_component * 0.5) + (brightness_component * 0.25) + (contrast_component * 0.25)))

    return {
        "manipulation_signal": float(fake_probability),
        "suspicious": fake_probability > 0.5,
        "method": "Lightweight fallback",
        "model_status": "Advanced ML model unavailable on this machine",
        "model_name": "Lightweight fallback",
        "model_version": "deterministic image-quality heuristic",
        "timestamp": datetime.utcnow().isoformat(),
        "status": "Advanced ML model unavailable on this machine; lightweight forensic fallback used.",
        "explanation": "A deterministic image-quality heuristic. It is not a trained deepfake classifier.",
    }

def analyze_image(image_path: str):
    """
    Analyzes an image to detect if it's a deepfake.
    Returns: (score, is_fake, details)
    Score is typically fake probability.
    """
    processor, model = get_deepfake_model()
    try:
        if processor == "deepfakebench" and model is not None:
            import torch

            image = Image.open(image_path).convert('RGB').resize((256, 256))
            pixels = np.asarray(image, dtype=np.float32) / 255.0
            tensor = torch.from_numpy(pixels).permute(2, 0, 1).unsqueeze(0)
            tensor = (tensor - 0.5) / 0.5
            device = next(model.parameters()).device
            with torch.no_grad():
                fake_prob = torch.softmax(model(tensor.to(device)), dim=1)[0, 1].item()
            return {
                "manipulation_signal": float(fake_prob),
                "method": "DeepfakeBench Xception",
                "model_status": "Advanced ML model available",
                "model_name": "DeepfakeBench Xception",
                "model_version": "v1.0.1 xception_best.pth (CC BY-NC 4.0)",
                "timestamp": datetime.utcnow().isoformat(),
                "predicted_label": "fake" if fake_prob > 0.5 else "real",
                "suspicious": fake_prob > 0.5,
                "note": "Face-manipulation detector; evaluate results as a signal, not proof.",
            }

        if processor is not None and model is not None:
            import torch

            img = Image.open(image_path).convert('RGB')
            device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
            inputs = processor(images=img, return_tensors="pt").to(device)

            with torch.no_grad():
                outputs = model(**inputs)
                logits = outputs.logits
                probs = torch.nn.functional.softmax(logits, dim=-1)

                predicted_class_idx = logits.argmax(-1).item()
                label = model.config.id2label[predicted_class_idx]

                fake_prob = 0.0
                real_prob = 0.0
                for k, v in model.config.id2label.items():
                    prob = probs[0][k].item()
                    if "fake" in v.lower():
                        fake_prob = prob
                    elif "real" in v.lower():
                        real_prob = prob

                if fake_prob == 0.0 and real_prob == 0.0:
                    if predicted_class_idx == 0:
                        fake_prob = probs[0][0].item()
                        real_prob = probs[0][1].item()
                    else:
                        fake_prob = probs[0][1].item()
                        real_prob = probs[0][0].item()

            return {
                "manipulation_signal": fake_prob,
                "method": "Hemg/Deepfake-Detection ViT",
                "model_status": "Advanced ML model available",
                "model_name": "Hemg/Deepfake-Detection",
                "model_version": "pretrained Hugging Face checkpoint",
                "timestamp": datetime.utcnow().isoformat(),
                "predicted_label": label,
                "suspicious": fake_prob > 0.5,
            }

        return _heuristic_fake_probability(image_path)
    except Exception as e:
        print(f"Error in deepfake detection: {e}")
        return _heuristic_fake_probability(image_path)

def analyze_frames(frame_paths: list):
    """
    Analyzes multiple frames and aggregates the score.
    frame_paths may be strings or dicts with path/timestamp.
    """
    results = []
    for item in frame_paths:
        if isinstance(item, dict):
            fp = item.get("path")
            timestamp = item.get("timestamp")
        else:
            fp = item
            timestamp = None
        res = analyze_image(fp)
        if res:
            res["frame_path"] = fp
            if timestamp is not None:
                res["timestamp"] = timestamp
            results.append(res)
            
    if not results:
        return None
        
    avg_fake_prob = sum(r["manipulation_signal"] for r in results) / len(results)
    
    return {
        "manipulation_signal": avg_fake_prob,
        "method": results[0].get("method", "Lightweight fallback"),
        "model_status": results[0].get("model_status", "Advanced ML model unavailable on this machine"),
        "model_name": results[0].get("model_name", "Lightweight fallback"),
        "model_version": results[0].get("model_version", "deterministic image-quality heuristic"),
        "timestamp": datetime.utcnow().isoformat(),
        "explanation": results[0].get("explanation", "Frame-level manipulation signal aggregation."),
        "suspicious": avg_fake_prob > 0.5,
        "frame_results": results
    }

def release_models():
    global _processor, _model, _model_name
    _processor = None
    _model = None
    _model_name = None
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
