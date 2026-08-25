"""Evaluate DeepTrace's detectors against a labelled dataset the operator supplies.

DeepTrace ships no accuracy figures. Every number in ``data/benchmark/latest.json``
is produced by this script running the real pipeline over real labelled files on
the machine it is run on, and ``GET /api/benchmark`` reports ``available: false``
until that file exists.

Expected layout (nothing is downloaded; you provide the media):

    data/benchmark/dataset/real/     authentic media  (label 0)
    data/benchmark/dataset/fake/     manipulated media (label 1)

Optional, for the face-matching threshold:

    data/benchmark/identity_pairs.csv
        image_a,image_b,same_person
        alice_1.jpg,alice_2.jpg,1
        alice_1.jpg,bob_1.jpg,0

    Paths are resolved relative to data/benchmark/pairs/ (or given absolute).

Usage:
    backend/venv/Scripts/python.exe scripts/benchmark.py
    backend/venv/Scripts/python.exe scripts/benchmark.py --threshold 0.5 --frames 8
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import time

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

from paths import BENCHMARK_DIR  # noqa: E402
from services import deepfake, forensics, identity  # noqa: E402

DATASET_DIR = os.path.join(BENCHMARK_DIR, "dataset")
PAIRS_CSV = os.path.join(BENCHMARK_DIR, "identity_pairs.csv")
PAIRS_DIR = os.path.join(BENCHMARK_DIR, "pairs")
LATEST_JSON = os.path.join(BENCHMARK_DIR, "latest.json")

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_EXT = {".mp4", ".avi", ".mov", ".mkv", ".webm"}

# Same operating point the application uses, so the reported metrics describe the
# behaviour a demo actually shows rather than a tuned-for-the-slide threshold.
DEFAULT_THRESHOLD = 0.50
IDENTITY_THRESHOLD = 0.60
SWEEP = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.80]


# --------------------------------------------------------------------------- #
# statistics (implemented here so the benchmark adds no runtime dependency)
# --------------------------------------------------------------------------- #

def wilson_interval(successes: int, total: int, z: float = 1.96):
    """95% Wilson score interval. Honest about small-sample uncertainty."""
    if total == 0:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z / denominator * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return [round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4)]


def roc_auc(scores: list[float], labels: list[int]):
    """Rank-based AUC (Mann-Whitney U), tie-corrected. None if a class is absent."""
    positives = [s for s, y in zip(scores, labels) if y == 1]
    negatives = [s for s, y in zip(scores, labels) if y == 0]
    if not positives or not negatives:
        return None

    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    index = 0
    while index < len(order):
        stop = index
        while stop + 1 < len(order) and scores[order[stop + 1]] == scores[order[index]]:
            stop += 1
        average = (index + stop) / 2 + 1  # 1-based, averaged across the tie group
        for position in range(index, stop + 1):
            ranks[order[position]] = average
        index = stop + 1

    positive_rank_sum = sum(rank for rank, y in zip(ranks, labels) if y == 1)
    n_pos, n_neg = len(positives), len(negatives)
    return round((positive_rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg), 4)


def confusion_at(scores: list[float], labels: list[int], threshold: float) -> dict:
    """Confusion matrix and the derived rates at one operating point."""
    tp = sum(1 for s, y in zip(scores, labels) if y == 1 and s >= threshold)
    fp = sum(1 for s, y in zip(scores, labels) if y == 0 and s >= threshold)
    tn = sum(1 for s, y in zip(scores, labels) if y == 0 and s < threshold)
    fn = sum(1 for s, y in zip(scores, labels) if y == 1 and s < threshold)
    total = tp + fp + tn + fn

    def ratio(numerator, denominator):
        return round(numerator / denominator, 4) if denominator else None

    precision = ratio(tp, tp + fp)
    recall = ratio(tp, tp + fn)
    f1 = None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = round(2 * precision * recall / (precision + recall), 4)

    return {
        "threshold": threshold,
        "true_positive": tp, "false_positive": fp,
        "true_negative": tn, "false_negative": fn,
        "accuracy": ratio(tp + tn, total),
        "accuracy_95_ci": wilson_interval(tp + tn, total),
        "precision": precision,
        "recall_sensitivity": recall,
        "specificity": ratio(tn, tn + fp),
        "f1": f1,
    }


def distribution(values: list[float]) -> dict | None:
    if not values:
        return None
    ordered = sorted(values)
    mean = sum(ordered) / len(ordered)
    variance = sum((v - mean) ** 2 for v in ordered) / len(ordered)
    return {
        "count": len(ordered),
        "mean": round(mean, 4),
        "std": round(math.sqrt(variance), 4),
        "min": round(ordered[0], 4),
        "median": round(ordered[len(ordered) // 2], 4),
        "max": round(ordered[-1], 4),
    }


# --------------------------------------------------------------------------- #
# dataset discovery
# --------------------------------------------------------------------------- #

def collect(directory: str) -> list[str]:
    """Media files directly inside ``directory``, sorted for a stable digest."""
    if not os.path.isdir(directory):
        return []
    found = []
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if os.path.isfile(path) and os.path.splitext(name)[1].lower() in (IMAGE_EXT | VIDEO_EXT):
            found.append(path)
    return found


def dataset_fingerprint(files: list[str]) -> str:
    """Digest of the evaluated file set, so results cannot be silently reused."""
    digest = hashlib.sha256()
    for path in files:
        digest.update(os.path.basename(path).encode("utf-8"))
        digest.update(str(os.path.getsize(path)).encode("utf-8"))
    return digest.hexdigest()[:16]


# --------------------------------------------------------------------------- #
# scoring one file through the real pipeline
# --------------------------------------------------------------------------- #

def score_file(path: str, frames: int) -> dict:
    """Manipulation signal for one file, via the same services the API uses."""
    extension = os.path.splitext(path)[1].lower()

    if extension in IMAGE_EXT:
        result = deepfake.analyze_image(path)
        if not result:
            return {"ok": False, "reason": "The manipulation model returned no result."}
        return {
            "ok": True,
            "score": float(result["manipulation_signal"]),
            "face_detected": bool(result.get("face_detected")),
            "method": result.get("method"),
            "frames_scored": 1,
        }

    if extension in VIDEO_EXT:
        if not forensics.ffmpeg_available():
            return {"ok": False, "reason": "FFmpeg is unavailable, so video frames cannot be sampled."}
        workspace = tempfile.mkdtemp(prefix="deeptrace_bench_")
        try:
            sampled = forensics.extract_sampled_frames(path, workspace, num_samples=frames)
            if not sampled:
                return {"ok": False, "reason": "No frames could be decoded from this file."}
            aggregate = deepfake.analyze_frames(sampled)
            if not aggregate:
                return {"ok": False, "reason": "The manipulation model returned no result for the sampled frames."}
            per_frame = aggregate.get("frame_results") or []
            return {
                "ok": True,
                # Mean over sampled frames: the same statistic the case view reports.
                "score": float(aggregate["manipulation_signal"]),
                "face_detected": any(item.get("face_detected") for item in per_frame),
                "method": aggregate.get("method"),
                "frames_scored": len(per_frame),
            }
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    return {"ok": False, "reason": f"Unsupported extension {extension}."}


def evaluate_manipulation(threshold: float, frames: int) -> dict | None:
    real_files = collect(os.path.join(DATASET_DIR, "real"))
    fake_files = collect(os.path.join(DATASET_DIR, "fake"))
    if not real_files and not fake_files:
        return None

    scores: list[float] = []
    labels: list[int] = []
    faces_found = 0
    skipped: list[dict] = []

    for label, files in ((0, real_files), (1, fake_files)):
        for path in files:
            name = os.path.basename(path)
            print(f"  [{'fake' if label else 'real'}] {name}", flush=True)
            outcome = score_file(path, frames)
            if not outcome["ok"]:
                skipped.append({"file": name, "label": label, "reason": outcome["reason"]})
                print(f"      skipped: {outcome['reason']}", flush=True)
                continue
            scores.append(outcome["score"])
            labels.append(label)
            faces_found += 1 if outcome["face_detected"] else 0
            print(f"      score {outcome['score']:.4f}"
                  f"  face={'yes' if outcome['face_detected'] else 'no'}"
                  f"  frames={outcome['frames_scored']}", flush=True)

    if not scores:
        return {
            "evaluated": 0,
            "note": "No file could be scored. The per-file reasons are listed under 'skipped'.",
            "skipped": skipped,
        }

    both_classes = 0 in labels and 1 in labels
    return {
        "evaluated": len(scores),
        "class_counts": {"real": labels.count(0), "fake": labels.count(1)},
        "skipped_count": len(skipped),
        "skipped": skipped,
        "model": deepfake.active_model_name(),
        "operating_point": confusion_at(scores, labels, threshold) if both_classes else None,
        "roc_auc": roc_auc(scores, labels),
        "threshold_sweep": [confusion_at(scores, labels, t) for t in SWEEP] if both_classes else [],
        "score_distribution": {
            "real": distribution([s for s, y in zip(scores, labels) if y == 0]),
            "fake": distribution([s for s, y in zip(scores, labels) if y == 1]),
        },
        "face_detection_rate": round(faces_found / len(scores), 4),
        "caveats": [
            f"Sample size is {len(scores)} file(s). Metrics from a sample this small have wide "
            "confidence intervals; the reported 95% Wilson interval quantifies that.",
            "The detector is trained on cropped aligned faces. Files where no face was located are "
            f"scored whole-frame and are less reliable; the face detection rate here was "
            f"{round(faces_found / len(scores) * 100, 1)}%.",
            "Video files are scored as the mean signal over sampled frames, so a short manipulated "
            "segment inside a long authentic clip is diluted.",
            "These figures describe this dataset on this machine only. They are not a general "
            "accuracy claim for DeepTrace or for the underlying model.",
        ] + ([] if both_classes else [
            "Only one class was present, so accuracy, precision, recall and AUC are undefined and "
            "reported as null. Provide files in both real/ and fake/ for a meaningful evaluation.",
        ]),
        "dataset_fingerprint": dataset_fingerprint(real_files + fake_files),
    }


# --------------------------------------------------------------------------- #
# optional: face-matching threshold
# --------------------------------------------------------------------------- #

def resolve_pair_path(value: str) -> str:
    value = value.strip()
    return value if os.path.isabs(value) else os.path.join(PAIRS_DIR, value)


def evaluate_identity() -> dict | None:
    if not os.path.isfile(PAIRS_CSV):
        return None

    rows = []
    with open(PAIRS_CSV, "r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                rows.append((
                    resolve_pair_path(row["image_a"]),
                    resolve_pair_path(row["image_b"]),
                    int(str(row["same_person"]).strip()),
                ))
            except (KeyError, TypeError, ValueError):
                continue
    if not rows:
        return {"evaluated": 0, "note": "identity_pairs.csv contained no usable rows "
                                        "(expected columns: image_a, image_b, same_person)."}

    cache: dict[str, object] = {}

    def embed(path: str):
        if path not in cache:
            cache[path] = identity.generate_face_embedding(path) if os.path.isfile(path) else None
        return cache[path]

    scores: list[float] = []
    labels: list[int] = []
    skipped: list[dict] = []
    for path_a, path_b, same in rows:
        embedding_a, embedding_b = embed(path_a), embed(path_b)
        if embedding_a is None or embedding_b is None:
            missing = os.path.basename(path_a if embedding_a is None else path_b)
            skipped.append({"pair": f"{os.path.basename(path_a)} / {os.path.basename(path_b)}",
                            "reason": f"No face embedding could be produced for {missing}."})
            continue
        similarity = float(identity.compare_faces(embedding_a, embedding_b))
        scores.append(similarity)
        labels.append(same)
        print(f"  [pair] {os.path.basename(path_a)} / {os.path.basename(path_b)}"
              f"  same={same}  similarity {similarity:.4f}", flush=True)

    if not scores:
        return {"evaluated": 0, "skipped": skipped,
                "note": "No pair could be scored; see 'skipped' for per-pair reasons."}

    both_classes = 0 in labels and 1 in labels
    return {
        "evaluated": len(scores),
        "pair_counts": {"same_person": labels.count(1), "different_person": labels.count(0)},
        "skipped_count": len(skipped),
        "skipped": skipped,
        "model": "facenet-pytorch InceptionResnetV1 (vggface2) with MTCNN detection",
        "operating_point": confusion_at(scores, labels, IDENTITY_THRESHOLD) if both_classes else None,
        "roc_auc": roc_auc(scores, labels),
        "similarity_distribution": {
            "same_person": distribution([s for s, y in zip(scores, labels) if y == 1]),
            "different_person": distribution([s for s, y in zip(scores, labels) if y == 0]),
        },
        "caveats": [
            f"Cosine similarity at the {IDENTITY_THRESHOLD} same-person threshold used by the "
            "application. Threshold choice trades false matches against missed matches.",
            "Pairs where no face could be detected are skipped, not counted as errors. That "
            "excludes exactly the hard cases, so these figures are optimistic relative to "
            "uncontrolled media.",
        ],
    }


# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate DeepTrace detectors on a labelled dataset.")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"Manipulation operating point (default {DEFAULT_THRESHOLD}).")
    parser.add_argument("--frames", type=int, default=12,
                        help="Frames sampled per video (default 12, matching the application).")
    args = parser.parse_args()

    os.makedirs(BENCHMARK_DIR, exist_ok=True)
    print("DeepTrace benchmark")
    print(f"  dataset: {DATASET_DIR}")

    started = time.time()
    print("\nManipulation detection")
    manipulation = evaluate_manipulation(args.threshold, max(1, args.frames))

    if manipulation is None:
        print("\n  No labelled media found.")
        print("  Nothing was written, so GET /api/benchmark keeps reporting available: false.")
        print("\n  To run an evaluation, place real files here:")
        print(f"    {os.path.join(DATASET_DIR, 'real')}")
        print("  and manipulated files here:")
        print(f"    {os.path.join(DATASET_DIR, 'fake')}")
        print("  then re-run this script. DeepTrace ships no pre-computed accuracy figures.")
        return 0

    print("\nFace matching")
    identity_metrics = evaluate_identity()
    if identity_metrics is None:
        print(f"  Skipped: no {os.path.basename(PAIRS_CSV)} present (optional).")

    payload = {
        "generated_at_utc": forensics.utc_now_iso(),
        "duration_seconds": round(time.time() - started, 1),
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "manipulation_model": deepfake.active_model_name(),
            "ffmpeg_available": forensics.ffmpeg_available(),
        },
        "manipulation_detection": manipulation,
        "identity_matching": identity_metrics,
        "provenance": (
            "Every figure above was computed by scripts/benchmark.py running the DeepTrace "
            "pipeline over the operator's own labelled files. No value is estimated, copied from "
            "a paper, or carried over from another dataset."
        ),
    }

    with open(LATEST_JSON, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    print(f"\nWrote {LATEST_JSON}")
    point = manipulation.get("operating_point")
    if point:
        print(f"  accuracy {point['accuracy']} (95% CI {point['accuracy_95_ci']})"
              f"  precision {point['precision']}  recall {point['recall_sensitivity']}"
              f"  AUC {manipulation.get('roc_auc')}  n={manipulation['evaluated']}")
    else:
        print("  Metrics are undefined for this dataset; see the caveats in the JSON.")
    deepfake.release_models()
    identity.release_models()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
