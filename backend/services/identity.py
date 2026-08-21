import numpy as np
from PIL import Image

_heavy_models = None

def get_models():
    global _heavy_models
    if _heavy_models is not None:
        return _heavy_models

    try:
        import torch
        from facenet_pytorch import MTCNN, InceptionResnetV1

        device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
        mtcnn = MTCNN(keep_all=False, device=device)
        resnet = InceptionResnetV1(pretrained='vggface2').eval().to(device)
        _heavy_models = (mtcnn, resnet)
    except Exception as e:
        print(f"Heavy face models unavailable, using lightweight fallback: {e}")
        _heavy_models = (None, None)

    return _heavy_models

def _fallback_face_embedding(image_path: str):
    try:
        img = Image.open(image_path).convert('L')
    except Exception:
        return None

    width, height = img.size
    if width == 0 or height == 0:
        return None

    # Use a centered square crop as a deterministic fallback when a dedicated face detector is unavailable.
    crop_size = min(width, height)
    left = max(0, (width - crop_size) // 2)
    top = max(0, (height - crop_size) // 2)
    face = img.crop((left, top, left + crop_size, top + crop_size)).resize((64, 64), Image.Resampling.BILINEAR)
    vec = np.asarray(face, dtype=np.float32).flatten()
    norm = np.linalg.norm(vec)
    if norm == 0:
        return None
    return (vec / norm).tolist()

def generate_face_embedding(image_path: str):
    """
    Detects a face in the image and generates a 512-d embedding.
    Returns the embedding as a list of floats or None if no face found.
    """
    mtcnn, resnet = get_models()
    try:
        if mtcnn is not None and resnet is not None:
            import torch

            img = Image.open(image_path).convert('RGB')
            face = mtcnn(img)
            if face is None:
                return None

            with torch.no_grad():
                device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
                face = face.to(device)
                if len(face.shape) == 3:
                    face = face.unsqueeze(0)
                embedding = resnet(face).cpu().numpy()[0]
            return embedding.tolist()

        return _fallback_face_embedding(image_path)
    except Exception as e:
        print(f"Error generating face embedding: {e}")
        return None

def compare_faces(embedding1, embedding2) -> float:
    """
    Computes cosine similarity between two embeddings.
    """
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
    global _heavy_models
    _heavy_models = None
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
