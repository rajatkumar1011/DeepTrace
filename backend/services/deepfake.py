"""Face-manipulation analysis.

Model selection order:
  1. DeepfakeBench Xception (local checkpoint) — the primary detector.
  2. ``Hemg/Deepfake-Detection`` ViT via transformers — used if the checkpoint is absent.
  3. A deterministic image-quality heuristic — clearly labelled, never presented
     as a trained classifier.

Preprocessing matters as much as the weights here: DeepfakeBench's checkpoint was
trained on cropped, aligned faces. Feeding it whole resized frames pushes the
input off-distribution, so a face crop is always attempted first and the outcome
is recorded per frame.
"""

import os
from datetime import datetime, timezone

import cv2
import numpy as np
from PIL import Image

_processor = None
_model = None
_model_name = None
_detector = None

_DEEPFAKEBENCH_WEIGHTS = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "pretrained_models", "deepfakebench", "xception_best.pth"
))

# The checkpoint's native input size and normalisation.
_INPUT_SIZE = 256
_FACE_MARGIN = 0.30


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_deepfakebench_xception():
    """Load DeepfakeBench's released Xception checkpoint when installed locally."""
    if not os.path.isfile(_DEEPFAKEBENCH_WEIGHTS):
        return None

    import torch
    from services.deepfakebench_xception import Xception

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    checkpoint = torch.load(_DEEPFAKEBENCH_WEIGHTS, map_location=device)
    state_dict = checkpoint.get("state_dict", checkpoint)
    state_dict = {key.removeprefix("backbone."): value for key, value in state_dict.items()}
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

            device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
            model_name = "Hemg/Deepfake-Detection"
            _processor = ViTImageProcessor.from_pretrained(model_name)
            _model = ViTForImageClassification.from_pretrained(model_name).eval().to(device)
            _model_name = model_name
        except Exception as error:
            print(f"Heavy deepfake model unavailable, using heuristic fallback: {error}")
            _processor = None
            _model = None
            _model_name = None
    return _processor, _model


def active_model_name() -> str:
    get_deepfake_model()
    return _model_name or "Lightweight fallback"


# ─── Face localisation ────────────────────────────────────────────────────────

def _mtcnn_detector():
    """Shared MTCNN instance, or None when facenet-pytorch is unavailable."""
    global _detector
    if _detector is None:
        try:
            import torch
            from facenet_pytorch import MTCNN

            device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
            _detector = MTCNN(keep_all=False, post_process=False, device=device)
        except Exception as error:
            print(f"MTCNN unavailable for face cropping: {error}")
            _detector = False
    return _detector or None


def _haar_box(image: Image.Image):
    cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
    cascade = cv2.CascadeClassifier(cascade_path)
    if cascade.empty():
        return None
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5, minSize=(48, 48))
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda box: box[2] * box[3])
    return [float(x), float(y), float(x + w), float(y + h)]


def _expand_and_crop(image: Image.Image, box) -> Image.Image:
    """Crop with margin so the model sees hairline/jaw context, as in training."""
    x1, y1, x2, y2 = box
    width, height = x2 - x1, y2 - y1
    pad_x, pad_y = width * _FACE_MARGIN, height * _FACE_MARGIN
    left = max(0, int(x1 - pad_x))
    top = max(0, int(y1 - pad_y))
    right = min(image.width, int(x2 + pad_x))
    bottom = min(image.height, int(y2 + pad_y))
    if right <= left or bottom <= top:
        return image
    return image.crop((left, top, right, bottom))


def locate_face(image: Image.Image) -> dict:
    """MTCNN, then Haar, then the whole frame. Always reports which path was used."""
    detector = _mtcnn_detector()
    if detector is not None:
        try:
            boxes, probs = detector.detect(image)
            if boxes is not None and len(boxes) > 0:
                best = int(np.argmax(probs)) if probs is not None else 0
                box = [float(v) for v in boxes[best]]
                confidence = float(probs[best]) if probs is not None else None
                return {
                    "face_detected": True,
                    "face_source": "mtcnn",
                    "face_box": [round(v, 1) for v in box],
                    "face_confidence": round(confidence, 4) if confidence is not None else None,
                    "crop": _expand_and_crop(image, box),
                }
        except Exception as error:
            print(f"MTCNN detection failed: {error}")

    box = _haar_box(image)
    if box:
        return {
            "face_detected": True,
            "face_source": "haar_cascade",
            "face_box": [round(v, 1) for v in box],
            "face_confidence": None,
            "crop": _expand_and_crop(image, box),
        }

    return {
        "face_detected": False,
        "face_source": "whole_frame",
        "face_box": None,
        "face_confidence": None,
        "crop": image,
    }


# ─── Heuristic fallback ───────────────────────────────────────────────────────

def _heuristic_fake_probability(image_path: str) -> dict | None:
    img = cv2.imread(image_path)
    if img is None:
        return None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
    brightness = float(np.mean(gray)) / 255.0
    contrast = float(np.std(gray)) / 128.0

    # Lower sharpness and unusual brightness/contrast are treated as more suspicious.
    sharpness_component = max(0.0, min(1.0, 1.0 - (blur_score / 400.0)))
    brightness_component = abs(brightness - 0.5)
    contrast_component = max(0.0, 1.0 - contrast)
    fake_probability = max(0.0, min(1.0, (sharpness_component * 0.5)
                                   + (brightness_component * 0.25)
                                   + (contrast_component * 0.25)))

    return {
        "manipulation_signal": float(fake_probability),
        "suspicious": fake_probability > 0.5,
        "method": "Lightweight fallback",
        "model_status": "Advanced ML model unavailable on this machine",
        "model_name": "Lightweight fallback",
        "model_version": "deterministic image-quality heuristic",
        "timestamp_utc": _utc_now(),
        "blur_variance": round(float(blur_score), 2),
        "face_detected": False,
        "face_source": "whole_frame",
        "status": "Advanced ML model unavailable on this machine; lightweight forensic fallback used.",
        "explanation": (
            "A deterministic image-quality heuristic based on sharpness, brightness and contrast. "
            "It is NOT a trained deepfake classifier and must not be read as one."
        ),
    }


# ─── Inference ────────────────────────────────────────────────────────────────

def analyze_image(image_path: str) -> dict | None:
    """Per-frame manipulation signal in [0, 1]. Higher = more manipulation evidence."""
    processor, model = get_deepfake_model()
    try:
        if processor == "deepfakebench" and model is not None:
            import torch

            with Image.open(image_path) as raw:
                image = raw.convert("RGB")
            located = locate_face(image)
            crop = located.pop("crop").resize((_INPUT_SIZE, _INPUT_SIZE), Image.Resampling.BILINEAR)

            pixels = np.asarray(crop, dtype=np.float32) / 255.0
            tensor = torch.from_numpy(pixels).permute(2, 0, 1).unsqueeze(0)
            tensor = (tensor - 0.5) / 0.5
            device = next(model.parameters()).device
            with torch.no_grad():
                probabilities = torch.softmax(model(tensor.to(device)), dim=1)[0]
            fake_prob = float(probabilities[1].item())

            gray = cv2.cvtColor(np.asarray(crop), cv2.COLOR_RGB2GRAY)
            return {
                "manipulation_signal": fake_prob,
                "class_probabilities": {
                    "real": round(float(probabilities[0].item()), 6),
                    "fake": round(fake_prob, 6),
                },
                "method": "DeepfakeBench Xception on detected face crop",
                "model_status": "Advanced ML model available",
                "model_name": "DeepfakeBench Xception",
                "model_version": "v1.0.1 xception_best.pth (CC BY-NC 4.0)",
                "timestamp_utc": _utc_now(),
                "predicted_label": "fake" if fake_prob > 0.5 else "real",
                "suspicious": fake_prob > 0.5,
                "input_size": _INPUT_SIZE,
                "blur_variance": round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 2),
                **located,
                "note": (
                    "Face-manipulation detector trained on cropped faces. Treat the output as a "
                    "forensic indicator, not proof."
                    if located["face_detected"] else
                    "No face was located in this frame, so the whole frame was scored. The detector "
                    "is trained on face crops, so this value is less reliable than a face-crop score."
                ),
            }

        if processor is not None and model is not None:
            import torch

            with Image.open(image_path) as raw:
                image = raw.convert("RGB")
            located = locate_face(image)
            crop = located.pop("crop")

            device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
            inputs = processor(images=crop, return_tensors="pt").to(device)
            with torch.no_grad():
                logits = model(**inputs).logits
                probs = torch.nn.functional.softmax(logits, dim=-1)

            predicted_idx = int(logits.argmax(-1).item())
            label = model.config.id2label[predicted_idx]
            fake_prob = real_prob = 0.0
            for index, name in model.config.id2label.items():
                value = float(probs[0][index].item())
                if "fake" in name.lower():
                    fake_prob = value
                elif "real" in name.lower():
                    real_prob = value
            if fake_prob == 0.0 and real_prob == 0.0:
                fake_prob = float(probs[0][predicted_idx].item())

            return {
                "manipulation_signal": fake_prob,
                "method": "Hemg/Deepfake-Detection ViT on detected face crop",
                "model_status": "Advanced ML model available",
                "model_name": "Hemg/Deepfake-Detection",
                "model_version": "pretrained Hugging Face checkpoint",
                "timestamp_utc": _utc_now(),
                "predicted_label": label,
                "suspicious": fake_prob > 0.5,
                **located,
            }

        return _heuristic_fake_probability(image_path)
    except Exception as error:
        print(f"Error in deepfake detection for {os.path.basename(image_path)}: {error}")
        fallback = _heuristic_fake_probability(image_path)
        if fallback:
            fallback["primary_model_error"] = str(error)[:300]
        return fallback


def analyze_frames(frame_items: list) -> dict | None:
    """Score every sampled frame and aggregate.

    Frames where a face was found are weighted as the primary evidence, because
    the detector is a *face*-manipulation model. Whole-frame scores are kept and
    reported but excluded from the headline aggregate when face crops exist.
    """
    results = []
    for item in frame_items:
        if isinstance(item, dict):
            path, timestamp, index = item.get("path"), item.get("timestamp"), item.get("index")
        else:
            path, timestamp, index = item, None, None
        if not path:
            continue
        result = analyze_image(path)
        if not result:
            continue
        result["frame_path"] = path
        result["frame_index"] = index
        if timestamp is not None:
            result["frame_timestamp_seconds"] = timestamp
        results.append(result)

    if not results:
        return None

    face_results = [r for r in results if r.get("face_detected")]
    scored = face_results or results
    signals = [float(r["manipulation_signal"]) for r in scored]
    mean_signal = sum(signals) / len(signals)
    suspicious_frames = [r for r in scored if float(r["manipulation_signal"]) > 0.5]

    first = results[0]
    return {
        "manipulation_signal": mean_signal,
        "max_frame_signal": max(signals),
        "min_frame_signal": min(signals),
        "signal_std": float(np.std(signals)),
        "frames_analyzed": len(results),
        "frames_with_face": len(face_results),
        "frames_scored_for_aggregate": len(scored),
        "suspicious_frame_count": len(suspicious_frames),
        "suspicious_frame_ratio": round(len(suspicious_frames) / len(scored), 4),
        "aggregate_basis": (
            "Mean over frames where a face was detected."
            if face_results else
            "Mean over all sampled frames — no face was detected in any frame, so scores are "
            "whole-frame and less reliable."
        ),
        "method": first.get("method", "Lightweight fallback"),
        "model_status": first.get("model_status", "Advanced ML model unavailable on this machine"),
        "model_name": first.get("model_name", "Lightweight fallback"),
        "model_version": first.get("model_version", "deterministic image-quality heuristic"),
        "timestamp_utc": _utc_now(),
        "explanation": first.get(
            "explanation",
            "Per-frame face-manipulation scores aggregated across evenly sampled frames.",
        ),
        "suspicious": mean_signal > 0.5,
        "frame_results": results,
    }


def release_models():
    global _processor, _model, _model_name, _detector
    _processor = None
    _model = None
    _model_name = None
    _detector = None
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
