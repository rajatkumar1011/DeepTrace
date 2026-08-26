"""Build a locally-constructed labelled evaluation set for scripts/benchmark.py.

Why this exists: precision, recall, F1 and false-positive rate cannot be computed
without ground truth, and DeepTrace ships no labelled corpus (public deepfake
datasets are licence-restricted and far too large to vendor). This script builds
a labelled set from media the operator already has, and — crucially — writes
``dataset/manifest.json`` recording exactly how every manipulated file was
produced, so the resulting metrics can never be mistaken for figures from a
public benchmark.

What it is NOT
--------------
The manipulations here are *conventional local edits*: copy-move cloning,
splicing from a donor image, region-confined recompression, face-region
smoothing and inpainting-based object removal. They are not GAN or diffusion
face swaps. A detector's score on this set says how it responds to local pixel
tampering; it does NOT transfer to face-swap deepfake accuracy. The manifest
carries that warning so it travels with the numbers.

Design detail that makes the set non-trivial
--------------------------------------------
Every manipulated file is written through the same final encoder as one of the
authentic files (JPEG q80 for images, H.264 CRF 23 for video), and the authentic
class contains re-encoded copies of untouched media. Without that control, the
label would correlate with "has been recompressed" and a detector could reach a
perfect score by keying on compression alone — a metric that measures nothing.

Usage:
    backend/venv/Scripts/python.exe scripts/make_eval_set.py --clean
    backend/venv/Scripts/python.exe scripts/make_eval_set.py --source C:/media --clean

Exit codes: 0 written, 3 no usable source media, 4 nothing could be produced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import cv2
import numpy as np

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

from paths import BENCHMARK_DIR  # noqa: E402
from services import forensics  # noqa: E402

DATASET_DIR = os.path.join(BENCHMARK_DIR, "dataset")
MANIFEST_NAME = "manifest.json"
GENERATOR = "scripts/make_eval_set.py (DeepTrace local evaluation-set builder, v1)"

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_EXT = {".mp4", ".avi", ".mov", ".mkv", ".webm"}

DEFAULT_SOURCES = [
    os.path.join(REPO_ROOT, "data", "demo"),
    os.path.join(REPO_ROOT, "data", "test_video.mp4"),
]

# Below this many files per class the set can prove the metric pipeline runs but
# cannot support a quotable accuracy figure; the manifest says so explicitly.
MIN_CREDIBLE_PER_CLASS = 30

# Shared final encode settings. Applied to both classes on purpose — see the
# module docstring on confound control.
IMAGE_ENCODE_QUALITY = 80
VIDEO_ENCODE_CRF = "23"
FFMPEG_TIMEOUT = 300

NO_SOURCES_EXIT = 3
NOTHING_PRODUCED_EXIT = 4


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def sha256_of(path: str) -> str | None:
    return forensics.calculate_sha256(path)


def stable_seed(*parts: str) -> int:
    """A seed derived from the inputs, so re-running reproduces the same set.

    Reproducibility is the point: an operator who re-runs this script must get
    byte-identical media, otherwise the dataset fingerprint in the benchmark
    results would change for no reason and the numbers could not be re-checked.
    """
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def safe_stem(path: str) -> str:
    """Filename-safe stem for an output name. Never reuses the operator's path."""
    stem = os.path.splitext(os.path.basename(path))[0]
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    return (cleaned or "media")[:48]


def media_type_of(path: str) -> str | None:
    extension = os.path.splitext(path)[1].lower()
    if extension in IMAGE_EXT:
        return "image"
    if extension in VIDEO_EXT:
        return "video"
    return None


def discover(sources: list[str], limit: int | None) -> list[str]:
    """Expand the --source arguments into a sorted list of media files."""
    found: list[str] = []
    for entry in sources:
        target = os.path.abspath(entry)
        if os.path.isfile(target):
            if media_type_of(target):
                found.append(target)
        elif os.path.isdir(target):
            for root, dirs, names in os.walk(target):
                dirs.sort()
                for name in sorted(names):
                    candidate = os.path.join(root, name)
                    if media_type_of(candidate):
                        found.append(candidate)
    unique = sorted(dict.fromkeys(found))
    return unique[:limit] if limit else unique


def run_ffmpeg(args: list[str]) -> tuple[bool, str]:
    """Invoke ffmpeg with an argv list, no shell, and a bounded timeout."""
    binary = forensics.ffmpeg_binary("ffmpeg")
    try:
        completed = subprocess.run(
            [binary, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *args],
            capture_output=True, timeout=FFMPEG_TIMEOUT, shell=False, check=False,
        )
    except FileNotFoundError:
        return False, "ffmpeg was not found."
    except subprocess.TimeoutExpired:
        return False, f"ffmpeg did not finish within {FFMPEG_TIMEOUT} s."
    except OSError as error:
        return False, f"ffmpeg could not be executed: {str(error)[:120]}"
    if completed.returncode != 0:
        message = (completed.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        return False, (message[-1][:200] if message else f"ffmpeg exited {completed.returncode}.")
    return True, "ok"


# --------------------------------------------------------------------------- #
# image manipulations
#
# Each takes a BGR array and a numpy Generator and returns (edited, detail) or
# (None, reason). Region geometry is recorded in `detail` so the manifest can
# state where the edit is, which is also the ground truth a localization claim
# would have to be checked against.
# --------------------------------------------------------------------------- #

def _region(rng: np.random.Generator, height: int, width: int,
            fraction: tuple[float, float] = (0.18, 0.34)) -> tuple[int, int, int, int]:
    box_h = int(height * rng.uniform(*fraction))
    box_w = int(width * rng.uniform(*fraction))
    box_h, box_w = max(box_h, 16), max(box_w, 16)
    top = int(rng.integers(0, max(height - box_h, 1)))
    left = int(rng.integers(0, max(width - box_w, 1)))
    return top, left, box_h, box_w


def _feather(base: np.ndarray, patch: np.ndarray, top: int, left: int, softness: int = 9) -> np.ndarray:
    """Alpha-blend a patch in with soft edges — how a real edit is finished.

    A hard paste leaves a step edge that any edge detector finds, which would
    make the set easier than reality. Feathering keeps the forgery plausible.
    """
    box_h, box_w = patch.shape[:2]
    mask = np.zeros((box_h, box_w), dtype=np.float32)
    inset = max(min(softness, box_h // 3, box_w // 3), 1)
    mask[inset:box_h - inset, inset:box_w - inset] = 1.0
    kernel = inset * 2 + 1
    mask = cv2.GaussianBlur(mask, (kernel, kernel), 0)[:, :, None]
    out = base.copy()
    region = out[top:top + box_h, left:left + box_w].astype(np.float32)
    blended = region * (1.0 - mask) + patch.astype(np.float32) * mask
    out[top:top + box_h, left:left + box_w] = np.clip(blended, 0, 255).astype(np.uint8)
    return out


def manipulate_copy_move(image: np.ndarray, rng: np.random.Generator, donor: np.ndarray | None):
    """Clone a region of the image over another region of the same image."""
    height, width = image.shape[:2]
    top, left, box_h, box_w = _region(rng, height, width)
    for _ in range(24):
        src_top = int(rng.integers(0, max(height - box_h, 1)))
        src_left = int(rng.integers(0, max(width - box_w, 1)))
        if abs(src_top - top) > box_h // 2 or abs(src_left - left) > box_w // 2:
            break
    else:
        return None, "No sufficiently distant source region was found."
    patch = image[src_top:src_top + box_h, src_left:src_left + box_w]
    edited = _feather(image, patch, top, left)
    return edited, {"region": [left, top, box_w, box_h], "copied_from": [src_left, src_top]}


def manipulate_splice(image: np.ndarray, rng: np.random.Generator, donor: np.ndarray | None):
    """Paste content from a different image in — the classic splice forgery."""
    if donor is None:
        return None, "No donor image was available to splice from."
    height, width = image.shape[:2]
    top, left, box_h, box_w = _region(rng, height, width)
    donor_resized = cv2.resize(donor, (box_w, box_h), interpolation=cv2.INTER_LINEAR)
    edited = _feather(image, donor_resized, top, left)
    return edited, {"region": [left, top, box_w, box_h], "donor_used": True}


def manipulate_region_recompress(image: np.ndarray, rng: np.random.Generator, donor: np.ndarray | None):
    """Recompress one region hard and paste it back.

    Localized double compression is what an edit-then-save workflow leaves behind
    in a real case, and it is the signal a block-level analysis looks for.
    """
    height, width = image.shape[:2]
    top, left, box_h, box_w = _region(rng, height, width, fraction=(0.25, 0.45))
    patch = image[top:top + box_h, left:left + box_w]
    ok, buffer = cv2.imencode(".jpg", patch, [int(cv2.IMWRITE_JPEG_QUALITY), 25])
    if not ok:
        return None, "The region could not be JPEG-encoded."
    decoded = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if decoded is None:
        return None, "The recompressed region could not be decoded."
    edited = image.copy()
    edited[top:top + box_h, left:left + box_w] = decoded
    return edited, {"region": [left, top, box_w, box_h], "region_jpeg_quality": 25}


def _face_box(image: np.ndarray) -> tuple[tuple[int, int, int, int], str]:
    """Locate a face with OpenCV's shipped cascade, else fall back to the centre.

    Which of the two happened is recorded, because "the manipulated area covers a
    face" and "the manipulated area covers the middle of the frame" are different
    claims and the manifest must not blur them.
    """
    cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
    if os.path.isfile(cascade_path):
        cascade = cv2.CascadeClassifier(cascade_path)
        if not cascade.empty():
            grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(grey, scaleFactor=1.1, minNeighbors=5, minSize=(32, 32))
            if len(faces) > 0:
                x, y, w, h = max(faces, key=lambda box: int(box[2]) * int(box[3]))
                return (int(x), int(y), int(w), int(h)), "haar_cascade"
    height, width = image.shape[:2]
    box_w, box_h = int(width * 0.4), int(height * 0.4)
    return ((width - box_w) // 2, (height - box_h) // 2, box_w, box_h), "centre_fallback"


def manipulate_face_smooth(image: np.ndarray, rng: np.random.Generator, donor: np.ndarray | None):
    """Wipe high-frequency texture from the face region.

    Loss of skin texture is the low-frequency footprint a synthesised or
    retouched face leaves. This reproduces that footprint without claiming to be
    a face swap.
    """
    (x, y, w, h), locator = _face_box(image)
    patch = image[y:y + h, x:x + w]
    if patch.size == 0:
        return None, "The face region was empty."
    smoothed = cv2.bilateralFilter(patch, d=15, sigmaColor=90, sigmaSpace=90)
    smoothed = cv2.GaussianBlur(smoothed, (5, 5), 0)
    edited = _feather(image, smoothed, y, x, softness=11)
    return edited, {"region": [x, y, w, h], "face_locator": locator}


def manipulate_inpaint_removal(image: np.ndarray, rng: np.random.Generator, donor: np.ndarray | None):
    """Remove content with inpainting — a deletion forgery rather than an addition."""
    height, width = image.shape[:2]
    top, left, box_h, box_w = _region(rng, height, width, fraction=(0.12, 0.22))
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.ellipse(mask, (left + box_w // 2, top + box_h // 2), (box_w // 2, box_h // 2),
                0, 0, 360, 255, -1)
    edited = cv2.inpaint(image, mask, inpaintRadius=5, flags=cv2.INPAINT_TELEA)
    if edited is None:
        return None, "Inpainting returned no result."
    return edited, {"region": [left, top, box_w, box_h], "method": "cv2.INPAINT_TELEA"}


MANIPULATIONS = [
    ("copy_move", manipulate_copy_move,
     "A rectangular region is cloned from elsewhere in the same image and blended in with a feathered mask."),
    ("splice", manipulate_splice,
     "A region from a different source image is scaled and blended into this one."),
    ("region_recompress", manipulate_region_recompress,
     "One region is JPEG-recompressed at quality 25 and pasted back, leaving localized double compression."),
    ("face_smooth", manipulate_face_smooth,
     "The face region is bilateral- and Gaussian-filtered, removing skin texture the way retouching or synthesis does."),
    ("inpaint_removal", manipulate_inpaint_removal,
     "An elliptical region is removed and filled by Telea inpainting."),
]

AUTHENTIC_VARIANTS = [
    ("original", "The source file's exact bytes, copied unchanged."),
    ("recompressed", "The unmodified source re-encoded with the same encoder settings as every manipulated file."),
    ("resized", "The unmodified source scaled to 90% and re-encoded — a legitimate processing step, not an edit."),
]


# --------------------------------------------------------------------------- #
# writers
# --------------------------------------------------------------------------- #

def write_image(image: np.ndarray, dest: str) -> bool:
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), IMAGE_ENCODE_QUALITY])
    if not ok:
        return False
    try:
        with open(dest, "wb") as handle:
            handle.write(buffer.tobytes())
    except OSError:
        return False
    return True


def encode_video_from_frames(frame_dir: str, fps: float, dest: str) -> tuple[bool, str]:
    """Encode a PNG frame sequence to H.264.

    ``-pix_fmt yuv420p`` is not optional: OpenCV writes BGR PNGs which libx264
    would otherwise encode as 4:4:4, a format most players and every real-world
    transcoder would not produce.
    """
    return run_ffmpeg([
        "-framerate", f"{max(fps, 1.0):.6f}",
        "-i", os.path.join(frame_dir, "frame_%06d.png"),
        "-c:v", "libx264", "-crf", VIDEO_ENCODE_CRF, "-preset", "veryfast",
        "-pix_fmt", "yuv420p", dest,
    ])


def decode_frames(path: str, frame_dir: str) -> tuple[int, float]:
    """Decode every frame to PNG. Returns (frame count, fps)."""
    capture = cv2.VideoCapture(path)
    if not capture.isOpened():
        return 0, 0.0
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    index = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        index += 1
        cv2.imwrite(os.path.join(frame_dir, f"frame_{index:06d}.png"), frame)
    capture.release()
    return index, float(fps)


# --------------------------------------------------------------------------- #
# per-source generation
# --------------------------------------------------------------------------- #

def build_image_items(source: str, donor: np.ndarray | None, real_dir: str, fake_dir: str,
                      seed_salt: str) -> tuple[list[dict], list[dict]]:
    """Authentic variants and manipulated variants of one still image."""
    items: list[dict] = []
    skipped: list[dict] = []
    image = cv2.imread(source, cv2.IMREAD_COLOR)
    if image is None:
        return [], [{"source": os.path.basename(source), "reason": "The image could not be decoded."}]

    stem = safe_stem(source)

    for variant, _description in AUTHENTIC_VARIANTS:
        dest = os.path.join(real_dir, f"{stem}__{variant}.jpg")
        if variant == "original":
            dest = os.path.join(real_dir, f"{stem}__original{os.path.splitext(source)[1].lower()}")
            try:
                shutil.copy2(source, dest)
            except OSError as error:
                skipped.append({"source": stem, "variant": variant, "reason": str(error)[:120]})
                continue
        elif variant == "recompressed":
            if not write_image(image, dest):
                skipped.append({"source": stem, "variant": variant, "reason": "JPEG encoding failed."})
                continue
        else:
            height, width = image.shape[:2]
            resized = cv2.resize(image, (max(int(width * 0.9), 16), max(int(height * 0.9), 16)),
                                 interpolation=cv2.INTER_AREA)
            if not write_image(resized, dest):
                skipped.append({"source": stem, "variant": variant, "reason": "JPEG encoding failed."})
                continue
        items.append({"path": os.path.relpath(dest, DATASET_DIR).replace("\\", "/"),
                      "label": "real", "family": variant, "media_type": "image",
                      "source": stem, "sha256": sha256_of(dest)})

    for family, function, _description in MANIPULATIONS:
        rng = np.random.default_rng(stable_seed(seed_salt, stem, family))
        edited, detail = function(image, rng, donor)
        if edited is None:
            skipped.append({"source": stem, "variant": family, "reason": detail})
            continue
        dest = os.path.join(fake_dir, f"{stem}__{family}.jpg")
        if not write_image(edited, dest):
            skipped.append({"source": stem, "variant": family, "reason": "JPEG encoding failed."})
            continue
        items.append({"path": os.path.relpath(dest, DATASET_DIR).replace("\\", "/"),
                      "label": "fake", "family": family, "media_type": "image",
                      "source": stem, "sha256": sha256_of(dest), "edit": detail})

    return items, skipped


def build_video_items(source: str, donor: np.ndarray | None, real_dir: str, fake_dir: str,
                      seed_salt: str, families: list[str]) -> tuple[list[dict], list[dict]]:
    """Authentic variants and temporally-localized manipulated variants of one clip."""
    items: list[dict] = []
    skipped: list[dict] = []
    stem = safe_stem(source)

    dest = os.path.join(real_dir, f"{stem}__original{os.path.splitext(source)[1].lower()}")
    try:
        shutil.copy2(source, dest)
        items.append({"path": os.path.relpath(dest, DATASET_DIR).replace("\\", "/"),
                      "label": "real", "family": "original", "media_type": "video",
                      "source": stem, "sha256": sha256_of(dest)})
    except OSError as error:
        skipped.append({"source": stem, "variant": "original", "reason": str(error)[:120]})

    workspace = tempfile.mkdtemp(prefix="deeptrace_eval_")
    try:
        frame_dir = os.path.join(workspace, "frames")
        os.makedirs(frame_dir, exist_ok=True)
        count, fps = decode_frames(source, frame_dir)
        if count == 0:
            skipped.append({"source": stem, "variant": "all", "reason": "No frames could be decoded."})
            return items, skipped

        # Authentic re-encode: the same encoder settings every manipulated clip
        # gets, so the label cannot be read off the compression history.
        recompressed = os.path.join(real_dir, f"{stem}__recompressed.mp4")
        ok, reason = encode_video_from_frames(frame_dir, fps, recompressed)
        if ok:
            items.append({"path": os.path.relpath(recompressed, DATASET_DIR).replace("\\", "/"),
                          "label": "real", "family": "recompressed", "media_type": "video",
                          "source": stem, "sha256": sha256_of(recompressed),
                          "frames": count})
        else:
            skipped.append({"source": stem, "variant": "recompressed", "reason": reason})

        for family, function, _description in MANIPULATIONS:
            if family not in families:
                continue
            rng = np.random.default_rng(stable_seed(seed_salt, stem, family))
            start = int(count * 0.3)
            end = max(int(count * 0.7), start + 1)
            edit_dir = os.path.join(workspace, f"edit_{family}")
            os.makedirs(edit_dir, exist_ok=True)

            detail = None
            failure = None
            for index in range(1, count + 1):
                frame_path = os.path.join(frame_dir, f"frame_{index:06d}.png")
                out_path = os.path.join(edit_dir, f"frame_{index:06d}.png")
                frame = cv2.imread(frame_path, cv2.IMREAD_COLOR)
                if frame is None:
                    failure = f"Frame {index} could not be re-read."
                    break
                if start < index <= end:
                    # One rng for the whole clip, so the edit region drifts
                    # frame to frame the way a hand-tracked edit would.
                    edited, frame_detail = function(frame, rng, donor)
                    if edited is None:
                        failure = frame_detail
                        break
                    detail = frame_detail
                    cv2.imwrite(out_path, edited)
                else:
                    cv2.imwrite(out_path, frame)
            if failure:
                skipped.append({"source": stem, "variant": family, "reason": failure})
                continue

            dest = os.path.join(fake_dir, f"{stem}__{family}.mp4")
            ok, reason = encode_video_from_frames(edit_dir, fps, dest)
            if not ok:
                skipped.append({"source": stem, "variant": family, "reason": reason})
                continue
            items.append({"path": os.path.relpath(dest, DATASET_DIR).replace("\\", "/"),
                          "label": "fake", "family": family, "media_type": "video",
                          "source": stem, "sha256": sha256_of(dest),
                          "frames": count, "frames_manipulated": end - start,
                          "frame_window": [start + 1, end], "edit": detail})
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    return items, skipped


# --------------------------------------------------------------------------- #
# manifest
# --------------------------------------------------------------------------- #

def build_manifest(items: list[dict], skipped: list[dict], sources: list[dict],
                   ffmpeg_ok: bool, seed_salt: str) -> dict:
    real = [item for item in items if item["label"] == "real"]
    fake = [item for item in items if item["label"] == "fake"]
    families_used = sorted({item["family"] for item in fake})

    family_notes = []
    for family, _function, description in MANIPULATIONS:
        count = sum(1 for item in fake if item["family"] == family)
        if count:
            family_notes.append({"name": family, "class": "manipulated",
                                 "description": description, "count": count})
    for variant, description in AUTHENTIC_VARIANTS:
        count = sum(1 for item in real if item["family"] == variant)
        if count:
            family_notes.append({"name": variant, "class": "authentic",
                                 "description": description, "count": count})

    smallest_class = min(len(real), len(fake))
    scale_warning = None
    if smallest_class < MIN_CREDIBLE_PER_CLASS:
        scale_warning = (
            f"The smaller class holds {smallest_class} file(s). At this size the confidence intervals "
            f"are wider than the differences they would need to resolve, so these metrics demonstrate "
            f"that the evaluation pipeline runs correctly — they are not a quotable accuracy claim. "
            f"Point --source at more media (at least {MIN_CREDIBLE_PER_CLASS} distinct originals per "
            f"class) before citing a number."
        )

    return {
        "generator": GENERATOR,
        "generated_at_utc": forensics.utc_now_iso(),
        "seed_salt": seed_salt,
        "construction": (
            f"{len(real)} authentic and {len(fake)} manipulated file(s) were generated from "
            f"{len(sources)} source file(s) on this machine. Authentic files are the untouched sources "
            f"plus re-encodes and a 90% resize of them. Manipulated files are the same sources with a "
            f"local edit applied ({', '.join(families_used) or 'none'}), then encoded with the same "
            f"settings as the authentic re-encodes. Every file's construction is recorded in 'items' "
            f"below, including the edited region."
        ),
        "manipulation_families": family_notes,
        "confound_control": (
            f"Manipulated stills are JPEG quality {IMAGE_ENCODE_QUALITY} and manipulated clips are H.264 "
            f"CRF {VIDEO_ENCODE_CRF}; the authentic class contains re-encodes of untouched media at exactly "
            f"those settings. Compression history therefore does not correlate with the label, so a detector "
            f"cannot score well by keying on 'has been recompressed'."
        ),
        "transferability_warning": (
            "These are conventional local edits — copy-move, splicing, region recompression, face-region "
            "smoothing, inpainting — not GAN or diffusion face swaps. Metrics measured here describe the "
            "detector's response to local pixel tampering and DO NOT transfer to face-swap deepfake "
            "accuracy. Do not present them as deepfake detection performance, and do not compare them "
            "against published FaceForensics++ or Celeb-DF figures."
        ),
        "independence_warning": (
            "Multiple files are derived from each source, so samples within a source are correlated. "
            "Confidence intervals computed as if every file were independent are therefore optimistic. "
            "The number of distinct originals, not the file count, is the honest sample size: "
            f"{len(sources)}."
        ),
        "scale_warning": scale_warning,
        "counts": {"real": len(real), "fake": len(fake), "distinct_sources": len(sources)},
        "ffmpeg_available": ffmpeg_ok,
        "source_media": sources,
        "items": items,
        "skipped": skipped,
    }


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a locally-constructed labelled evaluation set for scripts/benchmark.py.")
    parser.add_argument("--source", action="append", default=None,
                        help="File or directory to build from. Repeatable. "
                             "Defaults to data/demo/ and data/test_video.mp4.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Use at most this many source files.")
    parser.add_argument("--seed-salt", default="deeptrace-eval-v1",
                        help="Changes the random regions. Same salt reproduces the same set.")
    parser.add_argument("--clean", action="store_true",
                        help="Delete the existing dataset/real and dataset/fake first.")
    parser.add_argument("--video-families", default="copy_move,face_smooth",
                        help="Comma-separated manipulations to apply to video. Fewer is faster: "
                             "each one re-encodes the whole clip.")
    args = parser.parse_args()

    sources = discover(args.source or DEFAULT_SOURCES, args.limit)
    if not sources:
        where = ", ".join(args.source or DEFAULT_SOURCES)
        print(f"No image or video files were found under: {where}")
        print("Pass --source with a directory of media to build from.")
        return NO_SOURCES_EXIT

    real_dir = os.path.join(DATASET_DIR, "real")
    fake_dir = os.path.join(DATASET_DIR, "fake")
    if args.clean:
        # Scoped to the two generated directories, never to an operator path.
        for directory in (real_dir, fake_dir):
            shutil.rmtree(directory, ignore_errors=True)
    elif os.path.isdir(real_dir) and os.listdir(real_dir):
        print(f"{real_dir} already holds files. Re-run with --clean to rebuild, "
              f"or move the existing set aside.")
        return NOTHING_PRODUCED_EXIT
    os.makedirs(real_dir, exist_ok=True)
    os.makedirs(fake_dir, exist_ok=True)

    ffmpeg_ok = forensics.ffmpeg_available()
    video_families = [name.strip() for name in args.video_families.split(",") if name.strip()]

    # The donor for splices is the first still that is not the file being edited,
    # so a spliced region genuinely comes from different content.
    stills = [path for path in sources if media_type_of(path) == "image"]

    source_records: list[dict] = []
    items: list[dict] = []
    skipped: list[dict] = []

    print(f"Building a labelled evaluation set from {len(sources)} source file(s).")
    if not ffmpeg_ok:
        print("  ffmpeg is unavailable — video sources will be skipped.")

    for path in sources:
        media_type = media_type_of(path)
        record = {"name": os.path.basename(path), "media_type": media_type,
                  "sha256": sha256_of(path)}
        if media_type == "image":
            image = cv2.imread(path, cv2.IMREAD_COLOR)
            record["dimensions"] = None if image is None else [int(image.shape[1]), int(image.shape[0])]
            donor_path = next((candidate for candidate in stills if candidate != path), None)
            donor = cv2.imread(donor_path, cv2.IMREAD_COLOR) if donor_path else None
            if donor_path:
                record["splice_donor"] = os.path.basename(donor_path)
            produced, problems = build_image_items(path, donor, real_dir, fake_dir, args.seed_salt)
        elif media_type == "video":
            if not ffmpeg_ok:
                skipped.append({"source": safe_stem(path), "variant": "all",
                                "reason": "ffmpeg is unavailable, so video could not be re-encoded."})
                source_records.append(record)
                continue
            donor_path = stills[0] if stills else None
            donor = cv2.imread(donor_path, cv2.IMREAD_COLOR) if donor_path else None
            produced, problems = build_video_items(path, donor, real_dir, fake_dir,
                                                   args.seed_salt, video_families)
        else:
            continue

        items.extend(produced)
        skipped.extend(problems)
        source_records.append(record)
        print(f"  {os.path.basename(path)}: {len(produced)} file(s)"
              + (f", {len(problems)} skipped" if problems else ""))

    if not items:
        print("Nothing could be produced from the supplied sources.")
        return NOTHING_PRODUCED_EXIT

    manifest = build_manifest(items, skipped, source_records, ffmpeg_ok, args.seed_salt)
    manifest_path = os.path.join(DATASET_DIR, MANIFEST_NAME)
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)

    counts = manifest["counts"]
    print(f"\nWrote {counts['real']} authentic and {counts['fake']} manipulated file(s) "
          f"from {counts['distinct_sources']} source(s).")
    print(f"Manifest: {os.path.relpath(manifest_path, REPO_ROOT)}")
    if manifest["scale_warning"]:
        print(f"\nWARNING: {manifest['scale_warning']}")
    print("\nThese are local pixel edits, not face swaps. Do not present the resulting metrics as "
          "deepfake detection accuracy.")
    print("\nNext: backend/venv/Scripts/python.exe scripts/benchmark.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
