#!/usr/bin/env python3
"""Import a corpus the operator already holds a licence for into the eval set.

DeepTrace cannot download FaceForensics++ or Celeb-DF. Both require an accepted
agreement with their authors, and neither is redistributable, so the fetcher
deliberately does not touch them. But those are the corpora the manipulation
detector was actually trained on, and an in-distribution figure is the one a
reviewer most wants. This script closes that gap for an operator who has already
been granted a copy: it stages a balanced, fingerprinted sample of *their* files
into ``data/benchmark/dataset/`` and writes the manifest that makes the resulting
metrics quotable.

What it does and does not decide
--------------------------------
It never guesses a label. The operator names the authentic directories and the
manipulated directories explicitly, because directory placement becomes ground
truth, and ground truth invented by a script is worse than no ground truth. For
the same reason ``--corpus-name`` is required: a precision figure with no named
provenance cannot be defended, and this is the field that ends up in the report.

Where a manipulated tree has subdirectories, their names become families —
FaceForensics++ ships ``Deepfakes/``, ``Face2Face/``, ``FaceSwap/`` and
``NeuralTextures/``, and a per-family recall breakdown falls out of that for
free. One aggregate over four forgery methods describes none of them.

The confound check
------------------
The most common way an imported set produces a confidently wrong number is that
the two classes come from different places, so resolution, codec or file size
correlates with the label and the detector scores that instead of the forgery.
This script measures the two classes with the same probe the pipeline uses and
records what it finds. It does not block the import — the operator may have good
reason — but the finding travels with the metrics rather than staying in a
console message nobody kept.

Nothing here computes a metric. Run ``scripts/benchmark.py`` afterwards; every
figure comes from the real pipeline scoring these files.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import shutil
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))

# Windows consoles default to cp1252 and would crash on the dashes below.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from paths import BENCHMARK_DIR  # noqa: E402
from services import forensics  # noqa: E402

DATASET_DIR = os.path.join(BENCHMARK_DIR, "dataset")
MANIFEST_PATH = os.path.join(DATASET_DIR, "manifest.json")
GENERATOR = "scripts/import_eval_set.py (DeepTrace licensed-corpus importer, v1)"

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_EXT = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
MEDIA_EXT = IMAGE_EXT | VIDEO_EXT

# Below this a class is too small for the interval to be worth reading, which is
# the same floor make_eval_set.py applies.
MIN_CREDIBLE_PER_CLASS = 30

NOTHING_IMPORTED_EXIT = 3
REFUSED_EXIT = 4


# --------------------------------------------------------------------------- #
# discovery
# --------------------------------------------------------------------------- #

def media_under(directory: str) -> list[str]:
    """Every supported file below ``directory``, in a stable order."""
    found: list[str] = []
    for root, dirs, names in os.walk(directory):
        dirs.sort()
        for name in sorted(names):
            if os.path.splitext(name)[1].lower() in MEDIA_EXT:
                found.append(os.path.join(root, name))
    return found


def family_for(path: str, root: str, fallback: str) -> str:
    """The first subdirectory below ``root``, which is how corpora name methods.

    FaceForensics++ separates its forgery methods by directory, so the path is
    already carrying the information a per-family breakdown needs. Files sitting
    directly in the root have no method to read, and get the fallback.
    """
    relative = os.path.relpath(path, root)
    parts = relative.replace("\\", "/").split("/")
    return parts[0] if len(parts) > 1 else fallback


def gather(directories: list[str], label: str, fallback_family: str,
           per_class: int) -> list[dict]:
    """Balanced across families, so one large method cannot dominate the sample.

    Taking the first N files overall would fill the sample from whichever method
    happens to sort first and leave the others unmeasured. Drawing round-robin
    across families keeps every declared method present, which is the point of
    reporting them separately.
    """
    by_family: dict[str, list[dict]] = collections.defaultdict(list)
    for directory in directories:
        if not os.path.isdir(directory):
            print(f"  skipped (not a directory): {directory}")
            continue
        for path in media_under(directory):
            by_family[family_for(path, directory, fallback_family)].append(
                {"source_path": path, "label": label,
                 "family": family_for(path, directory, fallback_family)})

    if not by_family:
        return []

    picked: list[dict] = []
    families = sorted(by_family)
    index = 0
    while len(picked) < per_class:
        added = False
        for family in families:
            if index < len(by_family[family]) and len(picked) < per_class:
                picked.append(by_family[family][index])
                added = True
        if not added:
            break
        index += 1
    return picked


# --------------------------------------------------------------------------- #
# confound measurement
# --------------------------------------------------------------------------- #

def describe_class(items: list[dict]) -> dict:
    """Resolution, codec and size of one class, using the pipeline's own probe."""
    resolutions: collections.Counter = collections.Counter()
    codecs: collections.Counter = collections.Counter()
    extensions: collections.Counter = collections.Counter()
    sizes: list[int] = []

    for item in items:
        path = item["source_path"]
        extensions[os.path.splitext(path)[1].lower()] += 1
        try:
            sizes.append(os.path.getsize(path))
        except OSError:
            pass
        media_type = "image" if os.path.splitext(path)[1].lower() in IMAGE_EXT else "video"
        try:
            probe = forensics.collect_media_metadata(path, media_type) or {}
        except Exception:
            continue
        container = probe.get("container") or {}
        image = probe.get("image") or {}
        resolution = container.get("resolution") or image.get("resolution")
        if resolution:
            resolutions[str(resolution)] += 1
        codec = container.get("video_codec") or image.get("format")
        if codec:
            codecs[str(codec).lower()] += 1

    return {
        "count": len(items),
        "resolutions": dict(resolutions.most_common(6)),
        "codecs": dict(codecs.most_common(6)),
        "extensions": dict(extensions.most_common(6)),
        "median_bytes": sorted(sizes)[len(sizes) // 2] if sizes else None,
    }


def confound_note(real: dict, fake: dict, corpus: str) -> str:
    """State plainly whether encoding correlates with the label.

    A detector handed 1080p H.264 authentic clips and 256x256 JPEG forgeries can
    reach a high score without looking at a single face. Saying so next to the
    metric is the difference between a figure a reviewer can use and one they
    have to distrust.
    """
    problems = []
    for name, getter in (("resolution", "resolutions"), ("codec", "codecs"),
                         ("container/extension", "extensions")):
        real_keys, fake_keys = set(real[getter]), set(fake[getter])
        if real_keys and fake_keys and not (real_keys & fake_keys):
            problems.append(
                f"{name} does not overlap between the classes "
                f"(authentic {sorted(real_keys)}, manipulated {sorted(fake_keys)})")

    real_median, fake_median = real["median_bytes"], fake["median_bytes"]
    if real_median and fake_median:
        ratio = max(real_median, fake_median) / max(1, min(real_median, fake_median))
        if ratio >= 4:
            problems.append(
                f"median file size differs by {ratio:.1f}x "
                f"(authentic {real_median} bytes, manipulated {fake_median} bytes)")

    if not problems:
        return (
            f"Measured on import: the two classes drawn from {corpus} share resolution, codec and "
            f"container, and their median file sizes are within 4x. No encoding property observed "
            f"here separates the classes, so a score difference is more likely to be about the "
            f"content than about how the file was written. This is a check on gross confounds, not "
            f"a guarantee that none exists."
        )
    return (
        f"CONFOUND WARNING, measured on import: " + "; ".join(problems) + ". "
        f"A detector can score these classes apart without examining the manipulation at all, so "
        f"any metric computed on this set may be measuring encoding rather than forgery. Re-import "
        f"with authentic and manipulated media that share an encoding history — for "
        f"FaceForensics++ that means taking the authentic class from the same source videos as the "
        f"forgeries, at the same compression level."
    )


# --------------------------------------------------------------------------- #
# staging
# --------------------------------------------------------------------------- #

def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stage(items: list[dict], label: str) -> list[dict]:
    """Copy into the eval tree under a name that records where each file came from.

    Copies rather than links: a symlink needs elevation on Windows, and a hard
    link would let a later cleanup of the eval set reach into the operator's
    licensed corpus. A copy cannot.
    """
    destination_dir = os.path.join(DATASET_DIR, label)
    os.makedirs(destination_dir, exist_ok=True)

    staged: list[dict] = []
    for index, item in enumerate(items):
        source = item["source_path"]
        extension = os.path.splitext(source)[1].lower()
        safe_family = "".join(char if char.isalnum() else "_" for char in item["family"])[:40]
        name = f"{label}_{safe_family}_{index:05d}{extension}"
        destination = os.path.join(destination_dir, name)
        shutil.copy2(source, destination)
        staged.append({
            "path": f"{label}/{name}",
            "label": label,
            "family": item["family"],
            "media_type": "image" if extension in IMAGE_EXT else "video",
            # The operator's own path is deliberately not recorded: it would put a
            # local filesystem layout into an artifact that ends up in a report.
            "source": os.path.basename(source),
            "sha256": sha256_of(destination),
        })
        if (index + 1) % 25 == 0 or index + 1 == len(items):
            print(f"    staged {index + 1}/{len(items)}", flush=True)
    return staged


def build_manifest(real_items: list[dict], fake_items: list[dict], corpus: str,
                   licence: str, confound: str, class_profiles: dict) -> dict:
    families = sorted({item["family"] for item in fake_items})
    real_families = sorted({item["family"] for item in real_items})

    manifest = {
        "generator": GENERATOR,
        "generated_at_utc": forensics.utc_now_iso(),
        "source_corpus": corpus,
        "licence_note": licence,
        "construction": (
            f"{len(real_items)} authentic and {len(fake_items)} manipulated file(s) were copied from "
            f"a licensed local copy of {corpus} that the operator supplied. Labels come from the "
            f"directories the operator named on the command line; nothing in this repository "
            f"verified them. Sampling was balanced round-robin across "
            f"{len(families)} manipulated family/families so no single method dominates."
        ),
        "manipulation_families": (
            [{"name": name, "class": "manipulated",
              "description": f"Declared by the operator as directory '{name}' of {corpus}."}
             for name in families]
            + [{"name": name, "class": "authentic",
                "description": f"Declared by the operator as directory '{name}' of {corpus}."}
               for name in real_families]
        ),
        "confound_control": confound,
        "class_encoding_profile": class_profiles,
        "independence_warning": (
            "Files drawn from the same source video share a subject, lighting and camera. If this "
            "import took many crops or clips from few originals, the samples are not independent "
            "and the Wilson intervals below are narrower than the evidence supports. Prefer one "
            "file per source identity where the corpus layout allows it."
        ),
        "counts": {"real": len(real_items), "fake": len(fake_items)},
        "items": real_items + fake_items,
    }

    smaller = min(len(real_items), len(fake_items))
    if smaller < MIN_CREDIBLE_PER_CLASS:
        manifest["scale_warning"] = (
            f"The smaller class holds {smaller} file(s), below the {MIN_CREDIBLE_PER_CLASS} this "
            f"repository treats as the floor for a readable interval. Import more before quoting "
            f"any figure from this set."
        )

    if corpus.lower().replace(" ", "").replace("+", "") in {
            "faceforensics", "faceforensicspp", "ffpp", "ff", "celebdf", "celebdfv2"}:
        manifest["transferability_warning"] = (
            f"This is an in-distribution test: the Xception weights DeepTrace loads were trained on "
            f"{corpus}-family forgeries. An in-distribution result is the detector's ceiling, not "
            f"its field performance — quote it alongside a cross-generator figure, and alongside "
            f"the robustness artifact, or it will read as an accuracy claim for media the detector "
            f"has never seen."
        )
    else:
        manifest["transferability_warning"] = (
            f"Whether this is an in-distribution test depends on how {corpus} was produced. The "
            f"Xception weights DeepTrace loads were trained on FaceForensics++ face-swap and "
            f"reenactment forgeries; if {corpus} uses a different generator family, the result is a "
            f"cross-generator generalisation figure and must be labelled as one."
        )
    return manifest


# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stage a licensed local corpus into data/benchmark/dataset/ for evaluation.")
    parser.add_argument("--source", default=None,
                        help="A directory holding real/ and fake/ subdirectories. Shorthand for "
                             "--real <source>/real --fake <source>/fake.")
    parser.add_argument("--real", action="append", default=[], metavar="DIR",
                        help="A directory of authentic media. Repeatable.")
    parser.add_argument("--fake", action="append", default=[], metavar="DIR",
                        help="A directory of manipulated media. Repeatable. Its immediate "
                             "subdirectory names become manipulation families.")
    parser.add_argument("--corpus-name", default=None,
                        help="What this corpus is, e.g. 'FaceForensics++ c23'. Required: it becomes "
                             "the provenance line in every report that quotes these metrics.")
    parser.add_argument("--licence-note", default=None,
                        help="How the operator is licensed to use it. Defaults to a statement that "
                             "the operator holds the licence and DeepTrace does not redistribute.")
    parser.add_argument("--per-class", type=int, default=200,
                        help="Files to stage per class (default 200).")
    parser.add_argument("--clean", action="store_true",
                        help="Delete the existing dataset/real and dataset/fake first.")
    args = parser.parse_args()

    real_dirs = list(args.real)
    fake_dirs = list(args.fake)
    if args.source:
        real_dirs.append(os.path.join(args.source, "real"))
        fake_dirs.append(os.path.join(args.source, "fake"))

    if not real_dirs or not fake_dirs:
        print("Both an authentic and a manipulated source are required.")
        print("  python scripts/import_eval_set.py --source <dir with real/ and fake/> \\")
        print("      --corpus-name 'FaceForensics++ c23'")
        print("  python scripts/import_eval_set.py --real <dir> --fake <dir> \\")
        print("      --corpus-name 'Celeb-DF v2'")
        print("\nDirectory placement becomes ground truth, so this script will not guess which "
              "of two directories holds the forgeries.")
        return REFUSED_EXIT

    if not args.corpus_name:
        print("--corpus-name is required.")
        print("A precision figure with no named corpus cannot be defended by whoever presents it, "
              "and this value is what the report prints as the provenance of the metric.")
        return REFUSED_EXIT

    for label in ("real", "fake"):
        target = os.path.join(DATASET_DIR, label)
        if os.path.isdir(target) and os.listdir(target):
            if not args.clean:
                print(f"{target} already contains files.")
                print("Re-run with --clean to replace them, or evaluate the existing set with "
                      "scripts/benchmark.py. Mixing two corpora in one directory would make the "
                      "manifest describe files it did not stage.")
                return REFUSED_EXIT
            shutil.rmtree(target)

    per_class = max(1, args.per_class)
    print(f"Importing up to {per_class} file(s) per class from {args.corpus_name}.")

    print("\nAuthentic sources:")
    real_items = gather(real_dirs, "real", "authentic", per_class)
    print(f"  selected {len(real_items)} file(s) across "
          f"{len({item['family'] for item in real_items})} family/families")

    print("\nManipulated sources:")
    fake_items = gather(fake_dirs, "fake", "manipulated", per_class)
    print(f"  selected {len(fake_items)} file(s) across "
          f"{len({item['family'] for item in fake_items})} family/families")

    if not real_items or not fake_items:
        print("\nNothing was staged: at least one class found no supported media.")
        print(f"  Supported extensions: {', '.join(sorted(MEDIA_EXT))}")
        return NOTHING_IMPORTED_EXIT

    print("\nMeasuring encoding of both classes before staging.")
    profiles = {"authentic": describe_class(real_items), "manipulated": describe_class(fake_items)}
    confound = confound_note(profiles["authentic"], profiles["manipulated"], args.corpus_name)
    print(f"  {confound}")

    print("\nStaging authentic files.")
    staged_real = stage(real_items, "real")
    print("Staging manipulated files.")
    staged_fake = stage(fake_items, "fake")

    licence = args.licence_note or (
        f"The operator supplied a local copy of {args.corpus_name} that they are licensed to use. "
        f"DeepTrace neither downloads nor redistributes it; the staged copy lives in a gitignored "
        f"directory and is not committed.")

    manifest = build_manifest(staged_real, staged_fake, args.corpus_name, licence,
                              confound, profiles)
    os.makedirs(DATASET_DIR, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)

    print(f"\nStaged {len(staged_real)} authentic and {len(staged_fake)} manipulated file(s).")
    print(f"Manifest: {os.path.relpath(MANIFEST_PATH, REPO_ROOT)}")
    if manifest.get("scale_warning"):
        print(f"\n{manifest['scale_warning']}")
    print("\nThis media is gitignored and is not committed to the repository.")
    print("\nNext: backend/venv/Scripts/python.exe scripts/benchmark.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
