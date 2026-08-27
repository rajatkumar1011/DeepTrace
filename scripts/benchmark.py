"""Evaluate DeepTrace's detectors against a labelled dataset the operator supplies.

DeepTrace ships no accuracy figures. Every number in ``data/benchmark/latest.json``
is produced by this script running the real pipeline over real labelled files on
the machine it is run on, and ``GET /api/benchmark`` reports ``available: false``
until that file exists.

Expected layout (nothing is downloaded; you provide the media):

    data/benchmark/dataset/real/     authentic media  (label 0)
    data/benchmark/dataset/fake/     manipulated media (label 1)

Both are searched recursively, so an unpacked corpus such as FaceForensics++ can
be dropped in with its own directory structure intact. If
``data/benchmark/dataset/manifest.json`` is present (written by
``scripts/make_eval_set.py``) its construction record is copied into the results,
because a precision figure is only as trustworthy as the provenance of its
labels.

Optional, for the face-matching threshold:

    data/benchmark/identity_pairs.csv
        image_a,image_b,same_person
        alice_1.jpg,alice_2.jpg,1
        alice_1.jpg,bob_1.jpg,0

    Paths are resolved relative to data/benchmark/pairs/ (or given absolute).

Usage:
    backend/venv/Scripts/python.exe scripts/benchmark.py
    backend/venv/Scripts/python.exe scripts/benchmark.py --threshold 0.5 --frames 8

Exit codes: 0 evaluated and written, 3 no labelled media found (nothing written).
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
from services.statistics import wilson_interval as _wilson_interval  # noqa: E402

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

# Distinct exit code for "there was nothing to evaluate", so callers can tell a
# missing dataset apart from a completed evaluation.
NO_DATASET_EXIT = 3
# Distinct from success: the run completed and wrote a file, but the figures in it
# came from the heuristic fallback rather than a trained model. A CI step or the
# smoke test should be able to fail on that without parsing the JSON.
FALLBACK_EXIT = 5


# --------------------------------------------------------------------------- #
# statistics (implemented here so the benchmark adds no runtime dependency)
# --------------------------------------------------------------------------- #

def wilson_interval(successes: int, total: int, z: float = 1.96):
    """95% Wilson score interval. Honest about small-sample uncertainty.

    Delegates to services.statistics so the interval printed beside a benchmark
    figure, a robustness figure and an A/V alignment figure is the same
    calculation. Kept as a module-level name because that is how it is called
    throughout this script and by tests/test_benchmark_stats.py.
    """
    return _wilson_interval(successes, total, z)


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


# What a false positive *is* depends on what the positive class is, and the two
# evaluations in this file do not share one. Emitting the manipulation wording for
# identity pairs described a false match between two strangers as "an authentic
# file flagged as manipulated", which is not loose phrasing — it is the wrong
# claim about the wrong error, printed next to a correct number.
MANIPULATION_ERRORS = (
    "FP / (FP + TN) — the share of authentic files this operating point flags as manipulated.",
    "FN / (FN + TP) — the share of manipulated files this operating point clears as authentic.",
)
IDENTITY_ERRORS = (
    "FP / (FP + TN) — the share of different-person pairs this operating point declares a match. "
    "This is the error that would attribute a stranger's face to the complainant.",
    "FN / (FN + TP) — the share of genuine same-person pairs this operating point misses.",
)


def confusion_at(scores: list[float], labels: list[int], threshold: float,
                 errors: tuple[str, str] = MANIPULATION_ERRORS) -> dict:
    """Confusion matrix and the derived rates at one operating point.

    The false-positive rate is reported by name alongside specificity even though
    one is ``1 - other``: it is the error that would send an investigator after an
    innocent person, so a reviewer should be able to read it directly rather than
    subtract. ``errors`` carries the wording for that error and its opposite,
    because the caller is the only thing that knows what a positive means here.
    """
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
        # Precision and recall are binomial proportions like accuracy — TP over the
        # flagged files, and TP over the manipulated files — so each gets the same
        # Wilson interval. On a small dataset the interval is the number that keeps
        # a headline precision from being read as a settled figure.
        "precision_95_ci": wilson_interval(tp, tp + fp),
        "recall_sensitivity": recall,
        "recall_95_ci": wilson_interval(tp, tp + fn),
        "specificity": ratio(tn, tn + fp),
        "f1": f1,
        # Negatives wrongly flagged, over all negatives.
        "false_positive_rate": ratio(fp, fp + tn),
        "false_positive_rate_95_ci": wilson_interval(fp, fp + tn),
        # Positives missed, over all positives.
        "false_negative_rate": ratio(fn, fn + tp),
        "false_negative_rate_95_ci": wilson_interval(fn, fn + tp),
        "false_positive_rate_definition": errors[0],
        "false_negative_rate_definition": errors[1],
    }


def distribution(values: list[float]) -> dict | None:
    if not values:
        return None
    ordered = sorted(values)
    mean = sum(ordered) / len(ordered)
    variance = sum((v - mean) ** 2 for v in ordered) / len(ordered)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    return {
        "count": len(ordered),
        "mean": round(mean, 4),
        "std": round(math.sqrt(variance), 4),
        "min": round(ordered[0], 4),
        "median": round(median, 4),
        "max": round(ordered[-1], 4),
    }


# --------------------------------------------------------------------------- #
# dataset discovery
# --------------------------------------------------------------------------- #

def under_benchmark_dir(value: str) -> str:
    """Resolve a CLI path, treating a relative one as relative to the eval folder.

    Absolute paths are honoured as given: an operator with a licensed copy of
    FaceForensics++ on another drive must be able to point at it, and this is
    their own shell, not a request arriving from a browser. What this does buy is
    that the short forms used in the documentation — ``--dataset-dir
    dataset_localedits`` — land where a reader expects rather than in whatever
    directory they happened to be standing in.
    """
    return value if os.path.isabs(value) else os.path.abspath(os.path.join(BENCHMARK_DIR, value))


def collect(directory: str) -> list[str]:
    """Media files under ``directory``, recursively, sorted for a stable digest.

    Recursive because the public deepfake corpora ship nested — FaceForensics++
    uses ``manipulated_sequences/<method>/c23/videos/`` — and a loader that only
    read the top level would silently evaluate zero files from an unpacked
    dataset while still reporting success.
    """
    if not os.path.isdir(directory):
        return []
    found = []
    for root, dirs, names in os.walk(directory):
        dirs.sort()
        for name in sorted(names):
            if os.path.splitext(name)[1].lower() in (IMAGE_EXT | VIDEO_EXT):
                found.append(os.path.join(root, name))
    return sorted(found)


def dataset_fingerprint(files: list[str]) -> str:
    """Digest of the evaluated files' contents, so results cannot be silently reused.

    Content is hashed rather than name-and-size: swapping in a different file of
    the same length is exactly the substitution this fingerprint exists to catch.
    """
    digest = hashlib.sha256()
    for path in files:
        digest.update(os.path.relpath(path, BENCHMARK_DIR).replace("\\", "/").encode("utf-8"))
        try:
            with open(path, "rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
        except OSError:
            digest.update(b"<unreadable>")
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
        # No ffmpeg gate here: extract_sampled_frames decodes with cv2.VideoCapture
        # and never shells out, so gating on ffmpeg would skip every video on a
        # machine that can in fact score them. A file cv2 cannot open is reported
        # as undecodable below rather than silently dropped.
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


def _sanitise_transferability_warning(value):
    """Remove an obsolete inference from older dataset manifests.

    A cross-generator StyleGAN test cannot be called a mathematical lower bound on
    face-swap performance. Preserve the warning's scope without overstating what the
    experiment proves.
    """
    if not value:
        return value
    text = str(value)
    old = (
        "A result here is a lower bound on face-swap performance and must not be quoted as a "
        "FaceForensics++ or Celeb-DF number."
    )
    new = (
        "Performance on this StyleGAN corpus does not establish performance on face-swap or "
        "reenactment corpora and must not be quoted as a FaceForensics++ or Celeb-DF result."
    )
    return text.replace(old, new)


def dataset_provenance(real_files: list[str], fake_files: list[str], dataset_dir: str) -> dict:
    """Where the labels came from, stated in the results rather than assumed.

    A precision figure is only as trustworthy as its ground truth, so the payload
    has to say who decided which class each file belongs to. If the set was built
    by ``scripts/make_eval_set.py`` or downloaded by ``scripts/fetch_eval_data.py``
    its manifest is quoted verbatim; otherwise the honest answer is that the
    operator's directory placement is the only label, and the reader is told
    exactly that.
    """
    manifest_path = os.path.join(dataset_dir, "manifest.json")
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            declared = manifest.get("counts") or {}
            present = {"real": len(real_files), "fake": len(fake_files)}
            # A manifest left behind by an earlier build would describe files that
            # are no longer the ones being scored, which is the one way this
            # provenance block could mislead rather than inform. Say so if the
            # counts disagree instead of quoting the manifest as if it matched.
            mismatch = None
            if declared and (declared.get("real"), declared.get("fake")) != (present["real"], present["fake"]):
                mismatch = (
                    f"The manifest describes {declared.get('real')} authentic and {declared.get('fake')} "
                    f"manipulated file(s), but {present['real']} and {present['fake']} were scored. The "
                    f"manifest is stale relative to the directory; rebuild the set before quoting these "
                    f"figures."
                )
            return {
                "label_source": "manifest",
                "declared_by": manifest.get("generator", "unknown generator"),
                "generated_at_utc": manifest.get("generated_at_utc"),
                "construction": manifest.get("construction"),
                "manipulation_families": manifest.get("manipulation_families"),
                "confound_control": manifest.get("confound_control"),
                "transferability_warning": _sanitise_transferability_warning(
                    manifest.get("transferability_warning")
                ),
                "independence_warning": manifest.get("independence_warning"),
                "scale_warning": manifest.get("scale_warning"),
                "declared_counts": declared or None,
                "scored_counts": present,
                "manifest_matches_directory": mismatch is None,
                "manifest_mismatch": mismatch,
                "source_corpus": manifest.get("source_corpus"),
                "licence_note": manifest.get("licence_note"),
                "source_media": manifest.get("source_media"),
            }
        except (OSError, ValueError) as error:
            return {"label_source": "manifest_unreadable",
                    "note": f"dataset/manifest.json exists but could not be parsed: {error}"}
    return {
        "label_source": "directory_placement",
        "declared_by": "the operator who placed the files",
        "construction": (
            f"{len(real_files)} file(s) were read from dataset/real/ and treated as authentic, "
            f"{len(fake_files)} from dataset/fake/ and treated as manipulated. Directory placement "
            "is the only label; nothing in this repository verified it."
        ),
        "transferability_warning": (
            "Because the labels are unverified, these figures are only as correct as the operator's "
            "sorting. Ship dataset/manifest.json (or cite the public corpus and split used) if these "
            "numbers are going to be quoted anywhere."
        ),
    }


def pair_provenance(dataset_dir: str) -> dict:
    """Where the verification pairs came from, carried into the identity results.

    The manipulation figures already state their corpus; the identity figures were
    reporting a false-match rate with nothing naming the pairs it was measured over,
    which is the one number in this file most likely to be quoted at a reviewer. The
    fetcher records the pair corpus and revision in the dataset manifest, so read it
    from there rather than restating it here — a constant duplicated in two files
    drifts, and a drifted provenance claim is worse than none.
    """
    manifest_path = os.path.join(dataset_dir, "manifest.json")
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                pairs = (json.load(handle) or {}).get("identity_pairs")
            if isinstance(pairs, dict) and pairs.get("dataset"):
                return {
                    "label_source": "public_corpus_manifest",
                    "corpus": pairs,
                    "construction": (
                        f"Verification pairs from {pairs['dataset']} "
                        f"({pairs.get('config')}/{pairs.get('split')} split, revision "
                        f"{pairs.get('revision') or 'unrecorded'}): "
                        f"{pairs.get('same_person')} same-person and "
                        f"{pairs.get('different_person')} different-person pair(s). The pair labels "
                        f"are the corpus's own; nothing in this repository decided them."
                    ),
                }
        except (OSError, ValueError) as error:
            return {"label_source": "manifest_unreadable",
                    "note": f"dataset/manifest.json exists but could not be parsed: {error}"}
    return {
        "label_source": "operator_csv",
        "construction": (
            "Pair labels were read from identity_pairs.csv as supplied. No manifest names the corpus "
            "they came from, so these figures should not be quoted without one."
        ),
    }


def family_of(dataset_dir: str) -> dict[str, str]:
    """Map each dataset-relative path to the family its manifest declares.

    Without this the only reportable figure is one number over the whole set,
    which hides the thing a reviewer most needs to know: a detector can be
    excellent on one manipulation family and blind to another, and an aggregate
    that mixes them describes neither.
    """
    manifest_path = os.path.join(dataset_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        return {}
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError):
        return {}
    mapping: dict[str, str] = {}
    for item in manifest.get("items") or []:
        path, family = item.get("path"), item.get("family")
        if isinstance(path, str) and isinstance(family, str):
            mapping[path.replace("\\", "/")] = family
    return mapping


def per_family_breakdown(records: list[dict], threshold: float,
                         dataset_dir: str) -> list[dict] | None:
    """How the detector behaves on each declared family, separately.

    For a manipulated family the reportable figure is recall — the share of that
    family this operating point catches. For an authentic family it is the
    false-positive rate. They are deliberately not averaged into one column:
    they are different errors with different consequences for a complainant.
    """
    mapping = family_of(dataset_dir)
    if not mapping:
        return None

    grouped: dict[tuple[str, int], list[float]] = {}
    for record in records:
        relative = os.path.relpath(record["path"], dataset_dir).replace("\\", "/")
        family = mapping.get(relative)
        if family is None:
            continue
        grouped.setdefault((family, record["label"]), []).append(record["score"])

    rows = []
    for (family, label), scores in sorted(grouped.items()):
        flagged = sum(1 for score in scores if score >= threshold)
        rate = flagged / len(scores)
        rows.append({
            "family": family,
            "class": "manipulated" if label else "authentic",
            "evaluated": len(scores),
            "flagged": flagged,
            # One name per row rather than two half-empty columns, so a table of
            # these reads without the reader having to remember which is which.
            "metric": "recall" if label else "false_positive_rate",
            "value": round(rate, 4),
            "value_95_ci": [round(bound, 4) for bound in wilson_interval(flagged, len(scores))],
            "mean_score": round(sum(scores) / len(scores), 4),
        })
    return rows or None


def evaluate_manipulation(threshold: float, frames: int,
                          dataset_dir: str = DATASET_DIR) -> dict | None:
    real_files = collect(os.path.join(dataset_dir, "real"))
    fake_files = collect(os.path.join(dataset_dir, "fake"))
    if not real_files and not fake_files:
        return None

    scores: list[float] = []
    labels: list[int] = []
    records: list[dict] = []
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
            records.append({"path": path, "label": label, "score": outcome["score"],
                            "face_detected": bool(outcome["face_detected"])})
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
    model_name = deepfake.active_model_name()
    provenance = dataset_provenance(real_files, fake_files, dataset_dir)
    # Warnings the dataset itself carries are promoted into the caveat list, not
    # left buried in the provenance block. A reader who only skims the caveats is
    # the reader most likely to over-read the headline number.
    provenance_caveats = [
        text for text in (
            provenance.get("transferability_warning"),
            provenance.get("scale_warning"),
            provenance.get("independence_warning"),
            provenance.get("manifest_mismatch"),
        ) if text
    ]

    # When the labels come from a locally-built local-edit set, a near-chance AUC
    # is the *expected* outcome for a face-manipulation model, and saying so is
    # part of reporting the result correctly. Without this line a reader would
    # reasonably conclude the detector is broken, when what the number actually
    # shows is that it does not transfer outside its training distribution.
    declared_families = {
        entry.get("name") for entry in (provenance.get("manipulation_families") or [])
        if isinstance(entry, dict) and entry.get("class") == "manipulated"
    }
    local_edit_families = {"copy_move", "splice", "region_recompress", "inpaint_removal"}
    if declared_families & local_edit_families:
        provenance_caveats.append(
            f"The manipulations in this set are conventional local edits "
            f"({', '.join(sorted(declared_families))}) while '{model_name}' is a face-manipulation "
            f"detector. An AUC at or below 0.5 here means the model does not transfer to that class of "
            f"forgery — it is not evidence the model fails at the task it was trained for, and it is not "
            f"a deepfake detection score. Generic tampering is covered by the metadata, provenance and "
            f"consistency modules instead. For representative deepfake figures, populate dataset/real and "
            f"dataset/fake from a public face-swap corpus and re-run."
        )
    return {
        "evaluated": len(scores),
        "class_counts": {"real": labels.count(0), "fake": labels.count(1)},
        "skipped_count": len(skipped),
        "skipped": skipped,
        "model": model_name,
        "operating_point": confusion_at(scores, labels, threshold) if both_classes else None,
        "roc_auc": roc_auc(scores, labels),
        "threshold_sweep": [confusion_at(scores, labels, t) for t in SWEEP] if both_classes else [],
        "score_distribution": {
            "real": distribution([s for s, y in zip(scores, labels) if y == 0]),
            "fake": distribution([s for s, y in zip(scores, labels) if y == 1]),
        },
        "face_detection_rate": round(faces_found / len(scores), 4),
        "per_family": per_family_breakdown(records, threshold, dataset_dir),
        "dataset_provenance": provenance,
        "caveats": provenance_caveats + [
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
            "Only one class was present, so accuracy, precision, recall, the false-positive rate and "
            "AUC are undefined and reported as null. Provide files in both real/ and fake/ for a "
            "meaningful evaluation.",
        ]) + ([
            "The Xception deepfakebench weights were not loaded, so every score above came from the "
            f"deterministic image-statistics fallback ('{model_name}'). These metrics therefore "
            "measure a compression- and noise-residual heuristic, not a learned deepfake detector. "
            "Install the weights and re-run before quoting any figure as detection performance.",
        ] if "fallback" in model_name.lower() else []) + ([
            f"The classes are unbalanced ({labels.count(0)} real vs {labels.count(1)} fake). Accuracy "
            "is misleading under imbalance; read precision, recall and the false-positive rate.",
        ] if both_classes and min(labels.count(0), labels.count(1)) * 2 < max(labels.count(0), labels.count(1)) else []),
        "dataset_fingerprint": dataset_fingerprint(real_files + fake_files),
    }


# --------------------------------------------------------------------------- #
# optional: face-matching threshold
# --------------------------------------------------------------------------- #

def resolve_pair_path(value: str) -> str:
    value = value.strip()
    return value if os.path.isabs(value) else os.path.join(PAIRS_DIR, value)


def evaluate_identity(dataset_dir: str = DATASET_DIR) -> dict | None:
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
    identity_model = identity.active_model_name()
    return {
        "evaluated": len(scores),
        "pair_counts": {"same_person": labels.count(1), "different_person": labels.count(0)},
        "skipped_count": len(skipped),
        "skipped": skipped,
        "model": identity_model,
        "dataset_provenance": pair_provenance(dataset_dir),
        "operating_point": confusion_at(scores, labels, IDENTITY_THRESHOLD,
                                        IDENTITY_ERRORS) if both_classes else None,
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
            "A positive here means 'same person', so the false-positive rate is the rate at which "
            "two different people are declared a match — the error that would misidentify a victim.",
        ] + ([
            "FaceNet was not loaded, so these similarities come from the centred-greyscale-crop "
            "fallback, which measures pixel layout rather than facial identity. Do not read them as "
            "face-recognition performance.",
        ] if "fallback" in identity_model.lower() else []),
    }


# --------------------------------------------------------------------------- #

def main() -> int:
    default_frames = 12
    try:
        default_frames = max(1, int(os.environ.get("DEEPTRACE_FRAME_SAMPLES", "") or 12))
    except ValueError:
        pass

    parser = argparse.ArgumentParser(description="Evaluate DeepTrace detectors on a labelled dataset.")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"Manipulation operating point (default {DEFAULT_THRESHOLD}).")
    parser.add_argument("--frames", type=int, default=default_frames,
                        help=f"Frames sampled per video (default {default_frames}, "
                             "from DEEPTRACE_FRAME_SAMPLES so it matches the application).")
    # Two evaluation sets answer two different questions — an in-domain face
    # corpus and a locally-built local-edit set — and a reader is owed both. They
    # cannot share one output file, so the directory and the destination move
    # together.
    parser.add_argument("--dataset-dir", default=DATASET_DIR,
                        help=f"Labelled real/ and fake/ tree to evaluate (default {DATASET_DIR}).")
    parser.add_argument("--out", default=LATEST_JSON,
                        help=f"Where to write the metrics JSON (default {LATEST_JSON}). "
                             "Only the default is read by GET /api/benchmark.")
    parser.add_argument("--skip-identity", action="store_true",
                        help="Skip the face-matching pairs even if identity_pairs.csv exists.")
    args = parser.parse_args()

    dataset_dir = under_benchmark_dir(args.dataset_dir)
    out_path = under_benchmark_dir(args.out)

    os.makedirs(BENCHMARK_DIR, exist_ok=True)
    print("DeepTrace benchmark")
    print(f"  dataset: {dataset_dir}")

    started = time.time()
    print("\nManipulation detection")
    manipulation = evaluate_manipulation(args.threshold, max(1, args.frames), dataset_dir)

    if manipulation is None:
        print("\n  No labelled media found.")
        print("  Nothing was written, so GET /api/benchmark keeps reporting available: false.")
        print("\n  To run an evaluation, place real files here:")
        print(f"    {os.path.join(dataset_dir, 'real')}")
        print("  and manipulated files here:")
        print(f"    {os.path.join(dataset_dir, 'fake')}")
        print("  then re-run this script. DeepTrace ships no pre-computed accuracy figures.")
        print("\n  Or download a small openly-licensed face corpus:")
        print("    python scripts/fetch_eval_data.py")
        print("  Or build a locally-labelled set from authentic source media:")
        print("    python scripts/make_eval_set.py --source <folder of authentic media>")
        # Exit non-zero so a CI step or the smoke test can tell "no dataset" apart
        # from "evaluated successfully". Both used to return 0, which meant an
        # empty dataset directory looked exactly like a passing evaluation.
        return NO_DATASET_EXIT

    print("\nFace matching")
    identity_metrics = None
    if args.skip_identity:
        print("  Skipped: --skip-identity.")
    else:
        identity_metrics = evaluate_identity(dataset_dir)
        if identity_metrics is None:
            print(f"  Skipped: no {os.path.basename(PAIRS_CSV)} present (optional).")

    payload = {
        "generated_at_utc": forensics.utc_now_iso(),
        "duration_seconds": round(time.time() - started, 1),
        "environment": {
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "manipulation_model": deepfake.active_model_name(),
            "identity_model": identity.active_model_name(),
            "ffmpeg_available": forensics.ffmpeg_available(),
            "frames_per_video": max(1, args.frames),
        },
        "manipulation_detection": manipulation,
        "identity_matching": identity_metrics,
        "provenance": (
            "Every figure above was computed by scripts/benchmark.py running the DeepTrace "
            "pipeline over the operator's own labelled files. No value is estimated, copied from "
            "a paper, or carried over from another dataset."
        ),
    }

    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    print(f"\nWrote {out_path}")
    point = manipulation.get("operating_point")
    if point:
        print(f"  accuracy {point['accuracy']} (95% CI {point['accuracy_95_ci']})"
              f"  precision {point['precision']}  recall {point['recall_sensitivity']}"
              f"  F1 {point['f1']}")
        print(f"  false-positive rate {point['false_positive_rate']}"
              f" (95% CI {point['false_positive_rate_95_ci']})"
              f"  false-negative rate {point['false_negative_rate']}"
              f"  AUC {manipulation.get('roc_auc')}  n={manipulation['evaluated']}")
    else:
        print("  Metrics are undefined for this dataset; see the caveats in the JSON.")

    for row in manipulation.get("per_family") or []:
        print(f"  {row['family']:<20} {row['class']:<12} n={row['evaluated']:<4} "
              f"{row['metric']} {row['value']} (95% CI {row['value_95_ci']})")

    # The JSON already carries this in environment.* and in the caveats, but a
    # figure gets quoted long before anyone reads a caveat. Running the harness on
    # an interpreter without torch installed produces a complete, plausible,
    # entirely meaningless set of metrics in 3 seconds instead of 3 minutes, and
    # the only visible difference is a model name nobody was looking at. Say it
    # last, on stderr, and name the fix.
    checked = [("manipulation", deepfake.active_model_name())]
    if identity_metrics is not None:
        checked.append(("identity", identity.active_model_name()))
    fallbacks = [(label, name) for label, name in checked
                 if "fallback" in (name or "").lower()]
    exit_code = 0
    if fallbacks:
        print("", file=sys.stderr)
        print("  " + "!" * 74, file=sys.stderr)
        print("  THESE FIGURES ARE NOT DETECTION PERFORMANCE.", file=sys.stderr)
        for label, name in fallbacks:
            print(f"    The {label} model fell back to '{name}'.", file=sys.stderr)
        print("  The trained weights were not loaded, so the scores above come from a", file=sys.stderr)
        print("  deterministic image-statistics heuristic. Do not quote them anywhere.", file=sys.stderr)
        print("  Usual cause: the harness ran on an interpreter without torch. Use the", file=sys.stderr)
        print("  same environment the backend uses, e.g.:", file=sys.stderr)
        print("    backend/venv/Scripts/python scripts/benchmark.py", file=sys.stderr)
        print("  " + "!" * 74, file=sys.stderr)
        exit_code = FALLBACK_EXIT

    deepfake.release_models()
    identity.release_models()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
