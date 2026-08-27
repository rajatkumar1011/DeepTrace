"""Fetch an openly-licensed, representative face corpus for scripts/benchmark.py.

Why this exists
---------------
``scripts/make_eval_set.py`` builds a labelled set out of whatever media the
operator already has. That proves the metric pipeline runs, but it cannot answer
the question a reviewer actually asks — *how often is the detector right on
representative data?* — because the media in this repository is not
representative: it is one still with a face, a 64x64 avatar, and two synthetic
test clips with no faces in them at all. A face-manipulation detector scored on
that set is being asked the wrong question, and its near-chance result says
nothing about the task it was built for.

This script downloads a real, publicly redistributable corpus so the figures in
``data/benchmark/latest.json`` describe faces:

* **Manipulation** — ``TheKernel01/140k-Real-and-Fake-Faces`` (CC). Authentic
  class: photographs of real people. Manipulated class: StyleGAN-synthesised
  faces. Both classes are 256x256 aligned face crops from the same pipeline, so
  the label tracks *how the face was produced* rather than resolution or codec.

* **Identity matching** — ``logasja/lfw``, ``pairs`` config. This is the Labeled
  Faces in the Wild verification protocol: same-person and different-person
  pairs of unconstrained photographs. It is the standard way a face-matching
  threshold is reported, and it gives identity precision, recall, F1 and
  false-match rate rather than a similarity number with nothing to compare to.

What is deliberately NOT downloaded
-----------------------------------
FaceForensics++ and Celeb-DF are the in-domain corpora for the Xception detector
DeepTrace loads, and copies of them exist on public mirrors. They are not used
here: both require an accepted end-user licence agreement from their authors,
and the mirrors carry no licence metadata. ``scripts/import_eval_set.py``
exists so an operator who has legitimately obtained either one can point this
harness at their own copy in a single command.

Honesty properties
------------------
Nothing here computes or invents a metric. The script only places labelled media
on disk and records, in ``dataset/manifest.json``, exactly which dataset, which
revision, which split and which row each file came from, together with its
SHA-256. ``scripts/benchmark.py`` reads that manifest and quotes it, so a figure
can always be traced back to the bytes it was measured on.

Usage:
    backend/venv/Scripts/python.exe scripts/fetch_eval_data.py
    backend/venv/Scripts/python.exe scripts/fetch_eval_data.py --faces 400 --pairs 300
    backend/venv/Scripts/python.exe scripts/fetch_eval_data.py --clean --skip-pairs

Exit codes: 0 written, 3 nothing could be downloaded, 4 refused to overwrite.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

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
PAIRS_DIR = os.path.join(BENCHMARK_DIR, "pairs")
PAIRS_CSV = os.path.join(BENCHMARK_DIR, "identity_pairs.csv")
MANIFEST_PATH = os.path.join(DATASET_DIR, "manifest.json")

GENERATOR = "scripts/fetch_eval_data.py (DeepTrace public-corpus fetcher, v1)"
ROWS_API = "https://datasets-server.huggingface.co/rows"

# Only these hosts are contacted, and a redirect that leaves the set is refused.
# An unpinned fetcher that follows arbitrary redirects is an SSRF primitive; this
# one is pointed at a fixed, public, unauthenticated dataset API and stays there.
ALLOWED_HOSTS = {
    "datasets-server.huggingface.co",
    "huggingface.co",
    "cdn-lfs.huggingface.co",
    "cdn-lfs.hf.co",
    "cas-bridge.xethub.hf.co",
}

# A single face crop is tens of kilobytes. The cap is three orders of magnitude
# above that, so it never trips on real data and still bounds a hostile response.
MAX_IMAGE_BYTES = 12 * 1024 * 1024
PAGE_SIZE = 100
HTTP_TIMEOUT = 60
RETRIES = 3
RETRY_BACKOFF = 2.0

FACES_DATASET = "TheKernel01/140k-Real-and-Fake-Faces"
FACES_CONFIG = "default"
FACES_SPLIT = "test"
FACES_LICENCE = "cc"
FACES_URL = f"https://huggingface.co/datasets/{FACES_DATASET}"

PAIRS_DATASET = "logasja/lfw"
PAIRS_CONFIG = "pairs"
PAIRS_SPLIT = "test"
PAIRS_URL = f"https://huggingface.co/datasets/{PAIRS_DATASET}"

NOTHING_DOWNLOADED_EXIT = 3
REFUSED_EXIT = 4


# --------------------------------------------------------------------------- #
# transport
# --------------------------------------------------------------------------- #

def _check_host(url: str) -> str:
    """Reject anything that is not HTTPS to an allowlisted host."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise ValueError(f"Refusing a non-HTTPS URL: {parsed.scheme or 'no scheme'}")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"Refusing a URL outside the allowed hosts: {host or 'no host'}")
    return url


class _PinnedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects, but re-validate the host at every hop."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_host(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(
    _PinnedRedirectHandler(),
    urllib.request.HTTPSHandler(context=ssl.create_default_context()),
)
_opener.addheaders = [("User-Agent", "DeepTrace-eval-fetcher/1.0")]


def _get(url: str, limit: int) -> bytes:
    """GET with a byte ceiling, a timeout and bounded retries."""
    _check_host(url)
    last_error = ""
    for attempt in range(1, RETRIES + 1):
        try:
            with _opener.open(url, timeout=HTTP_TIMEOUT) as response:
                declared = response.headers.get("Content-Length")
                if declared and declared.isdigit() and int(declared) > limit:
                    raise ValueError(f"the response declares {int(declared)} bytes, over the {limit} cap")
                # read one byte past the cap so an over-long body is detected
                # rather than silently truncated into a corrupt file.
                payload = response.read(limit + 1)
            if len(payload) > limit:
                raise ValueError(f"the response exceeded the {limit} byte cap")
            if not payload:
                raise ValueError("the response was empty")
            return payload
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as error:
            last_error = str(error)[:160]
            if attempt < RETRIES:
                time.sleep(RETRY_BACKOFF * attempt)
    raise RuntimeError(f"{last_error}")


def fetch_page(dataset: str, config: str, split: str, offset: int, length: int) -> dict:
    """One page of rows from the public datasets-server API."""
    query = urllib.parse.urlencode(
        {"dataset": dataset, "config": config, "split": split,
         "offset": offset, "length": length})
    payload = _get(f"{ROWS_API}?{query}", 32 * 1024 * 1024)
    return json.loads(payload.decode("utf-8"))


def image_url(cell) -> str | None:
    """The direct URL for an Image cell, whatever shape the API returned it in."""
    if isinstance(cell, dict):
        for key in ("src", "url"):
            value = cell.get(key)
            if isinstance(value, str) and value:
                return value
    return cell if isinstance(cell, str) and cell.startswith("https://") else None


def save_image(url: str, dest: str) -> tuple[bool, str]:
    """Download one image to ``dest``. Written whole or not at all."""
    try:
        payload = _get(url, MAX_IMAGE_BYTES)
    except (RuntimeError, ValueError) as error:
        return False, str(error)[:160]
    partial = dest + ".part"
    try:
        with open(partial, "wb") as handle:
            handle.write(payload)
        os.replace(partial, dest)
    except OSError as error:
        try:
            os.remove(partial)
        except OSError:
            pass
        return False, str(error)[:160]
    return True, "ok"


def class_names(features: list, column: str) -> list[str]:
    """The ClassLabel names for ``column``, so an integer code can be resolved.

    Reading the names from the API rather than assuming ``0 == real`` matters: an
    inverted label mapping would produce a confident, completely wrong precision
    figure, which is the single worst failure this script could have.
    """
    for feature in features or []:
        if feature.get("name") == column:
            return list((feature.get("type") or {}).get("names") or [])
    return []


# --------------------------------------------------------------------------- #
# manipulation set
# --------------------------------------------------------------------------- #

def fetch_faces(target_per_class: int) -> tuple[list[dict], list[dict], dict]:
    """Download a balanced real/fake face set. Returns (items, skipped, meta)."""
    real_dir = os.path.join(DATASET_DIR, "real")
    fake_dir = os.path.join(DATASET_DIR, "fake")
    os.makedirs(real_dir, exist_ok=True)
    os.makedirs(fake_dir, exist_ok=True)

    items: list[dict] = []
    skipped: list[dict] = []
    counts = {"real": 0, "fake": 0}
    offset = 0
    revision = None
    label_names: list[str] = []
    generator_names: list[str] = []
    total_rows = None

    print(f"Downloading up to {target_per_class} authentic and {target_per_class} "
          f"synthesised face(s) from {FACES_DATASET} [{FACES_SPLIT}].")

    while counts["real"] < target_per_class or counts["fake"] < target_per_class:
        try:
            page = fetch_page(FACES_DATASET, FACES_CONFIG, FACES_SPLIT, offset, PAGE_SIZE)
        except (RuntimeError, ValueError, json.JSONDecodeError) as error:
            skipped.append({"offset": offset, "reason": f"The row page could not be read: {error}"})
            break

        rows = page.get("rows") or []
        if not rows:
            break
        if not label_names:
            label_names = class_names(page.get("features"), "label")
            generator_names = class_names(page.get("features"), "generator")
            total_rows = page.get("num_rows_total")
            if sorted(label_names) != ["fake", "real"]:
                raise SystemExit(
                    f"{FACES_DATASET} reported label classes {label_names!r}, not the expected "
                    f"real/fake pair. Refusing to guess which integer means 'fake': a wrong "
                    f"mapping would invert every metric. Inspect the dataset card and update "
                    f"this script."
                )

        for row in rows:
            record = row.get("row") or {}
            row_index = row.get("row_idx", offset)
            try:
                label_name = label_names[int(record.get("label"))]
            except (TypeError, ValueError, IndexError):
                skipped.append({"row": row_index, "reason": "The label could not be resolved."})
                continue

            bucket = "fake" if label_name == "fake" else "real"
            if counts[bucket] >= target_per_class:
                continue

            url = image_url(record.get("image"))
            if not url:
                skipped.append({"row": row_index, "reason": "The row carried no image URL."})
                continue
            if not revision:
                revision = _revision_from(url)

            generator = None
            try:
                generator = generator_names[int(record.get("generator"))]
            except (TypeError, ValueError, IndexError):
                pass

            name = f"lfw140k_{FACES_SPLIT}_{row_index:06d}_{bucket}.jpg"
            dest = os.path.join(fake_dir if bucket == "fake" else real_dir, name)
            ok, reason = save_image(url, dest)
            if not ok:
                skipped.append({"row": row_index, "reason": reason})
                continue

            counts[bucket] += 1
            items.append({
                "path": os.path.relpath(dest, DATASET_DIR).replace("\\", "/"),
                "label": bucket,
                # The generator column is the honest family name here: the
                # 'manipulation' is synthesis, and saying StyleGAN rather than
                # 'fake' is what lets a reader judge transferability.
                "family": (generator or ("StyleGAN" if bucket == "fake" else "Real")),
                "media_type": "image",
                "source": f"{FACES_DATASET}#{FACES_SPLIT}",
                "source_row": row_index,
                "sha256": forensics.calculate_sha256(dest),
            })

        offset += len(rows)
        print(f"  {counts['real']} authentic, {counts['fake']} synthesised "
              f"(read {offset} row(s))", flush=True)
        if total_rows and offset >= total_rows:
            break

    meta = {
        "dataset": FACES_DATASET,
        "dataset_url": FACES_URL,
        "config": FACES_CONFIG,
        "split": FACES_SPLIT,
        "revision": revision,
        "licence": FACES_LICENCE,
        "rows_read": offset,
        "rows_available": total_rows,
        "label_classes": label_names,
        "generator_classes": generator_names,
    }
    return items, skipped, meta


def _revision_from(url: str) -> str | None:
    """The dataset revision embedded in a cached-asset URL, if it is there.

    Recording it means a later re-run can be compared against this one rather
    than merely assumed to match.
    """
    parts = [segment for segment in urllib.parse.urlsplit(url).path.split("/") if segment]
    for segment in parts:
        if len(segment) == 40 and all(character in "0123456789abcdef" for character in segment):
            return segment
    return None


# --------------------------------------------------------------------------- #
# identity pairs
# --------------------------------------------------------------------------- #

def fetch_pairs(target: int) -> tuple[list[dict], list[dict], dict]:
    """Download LFW verification pairs and write identity_pairs.csv."""
    os.makedirs(PAIRS_DIR, exist_ok=True)

    rows_out: list[dict] = []
    skipped: list[dict] = []
    offset = 0
    revision = None
    pair_names: list[str] = []
    total_rows = None
    same_count = 0
    different_count = 0
    # Half each way: LFW lists matched pairs before mismatched ones, so taking
    # the first N rows would collect one class only and make the false-match
    # rate undefined.
    per_class = max(target // 2, 1)

    print(f"Downloading up to {per_class} same-person and {per_class} different-person "
          f"pair(s) from {PAIRS_DATASET} [{PAIRS_CONFIG}/{PAIRS_SPLIT}].")

    while same_count < per_class or different_count < per_class:
        try:
            page = fetch_page(PAIRS_DATASET, PAIRS_CONFIG, PAIRS_SPLIT, offset, PAGE_SIZE)
        except (RuntimeError, ValueError, json.JSONDecodeError) as error:
            skipped.append({"offset": offset, "reason": f"The row page could not be read: {error}"})
            break

        rows = page.get("rows") or []
        if not rows:
            break
        if not pair_names:
            pair_names = class_names(page.get("features"), "pair")
            total_rows = page.get("num_rows_total")

        for row in rows:
            record = row.get("row") or {}
            row_index = row.get("row_idx", offset)
            try:
                same = int(record.get("pair"))
            except (TypeError, ValueError):
                skipped.append({"row": row_index, "reason": "The pair label could not be resolved."})
                continue
            if same not in (0, 1):
                skipped.append({"row": row_index, "reason": f"Unexpected pair label {same!r}."})
                continue
            if same == 1 and same_count >= per_class:
                continue
            if same == 0 and different_count >= per_class:
                continue

            url_a, url_b = image_url(record.get("img_0")), image_url(record.get("img_1"))
            if not url_a or not url_b:
                skipped.append({"row": row_index, "reason": "The row was missing one of its images."})
                continue
            if not revision:
                revision = _revision_from(url_a)

            stem = f"lfw_{PAIRS_SPLIT}_{row_index:05d}"
            name_a, name_b = f"{stem}_a.jpg", f"{stem}_b.jpg"
            ok_a, reason_a = save_image(url_a, os.path.join(PAIRS_DIR, name_a))
            if not ok_a:
                skipped.append({"row": row_index, "reason": reason_a})
                continue
            ok_b, reason_b = save_image(url_b, os.path.join(PAIRS_DIR, name_b))
            if not ok_b:
                skipped.append({"row": row_index, "reason": reason_b})
                continue

            rows_out.append({"image_a": name_a, "image_b": name_b, "same_person": same})
            if same:
                same_count += 1
            else:
                different_count += 1

        offset += len(rows)
        print(f"  {same_count} same-person, {different_count} different-person "
              f"(read {offset} row(s))", flush=True)
        if total_rows and offset >= total_rows:
            break

    if rows_out:
        with open(PAIRS_CSV, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["image_a", "image_b", "same_person"])
            writer.writeheader()
            writer.writerows(rows_out)

    meta = {
        "dataset": PAIRS_DATASET,
        "dataset_url": PAIRS_URL,
        "config": PAIRS_CONFIG,
        "split": PAIRS_SPLIT,
        "revision": revision,
        "rows_read": offset,
        "rows_available": total_rows,
        "same_person": same_count,
        "different_person": different_count,
    }
    return rows_out, skipped, meta


# --------------------------------------------------------------------------- #
# manifest
# --------------------------------------------------------------------------- #

def build_manifest(items: list[dict], skipped: list[dict], faces_meta: dict,
                   pairs_meta: dict | None) -> dict:
    """The provenance record scripts/benchmark.py quotes into its results."""
    real = [item for item in items if item["label"] == "real"]
    fake = [item for item in items if item["label"] == "fake"]

    families = []
    for name in sorted({item["family"] for item in fake}):
        families.append({
            "name": name, "class": "manipulated",
            "count": sum(1 for item in fake if item["family"] == name),
            "description": (
                "Face synthesised in full by a generative adversarial network. No "
                "photograph of this person exists; the identity itself is fabricated."
                if name.lower() == "stylegan" else
                f"Manipulated class '{name}' as labelled by the source dataset."),
        })
    for name in sorted({item["family"] for item in real}):
        families.append({
            "name": name, "class": "authentic",
            "count": sum(1 for item in real if item["family"] == name),
            "description": "Photograph of a real person, unmodified, as labelled by the source dataset.",
        })

    smallest = min(len(real), len(fake)) if items else 0
    scale_warning = None
    if smallest < 100:
        scale_warning = (
            f"The smaller class holds {smallest} file(s). The 95% intervals reported alongside each "
            f"metric are correspondingly wide. Re-run with --faces 500 or more before quoting a "
            f"figure to two decimal places."
        )

    return {
        "generator": GENERATOR,
        "generated_at_utc": forensics.utc_now_iso(),
        "construction": (
            f"{len(real)} authentic and {len(fake)} synthesised face image(s) were downloaded from the "
            f"public dataset {faces_meta['dataset']} ({faces_meta['config']}/{faces_meta['split']} split, "
            f"revision {faces_meta.get('revision') or 'unrecorded'}). The authentic class is photographs "
            f"of real people; the manipulated class is StyleGAN-generated faces. Labels are the source "
            f"dataset's own, read from its ClassLabel names rather than inferred from directory placement. "
            f"Every file's source row index and SHA-256 are recorded under 'items' below."
        ),
        "source_corpus": faces_meta,
        "identity_pairs": pairs_meta,
        "manipulation_families": families,
        "confound_control": (
            "Both classes are 256x256 aligned face crops distributed as JPEG by the same source "
            "dataset, so neither resolution, alignment nor codec correlates with the label. What "
            "differs between the classes is how the face was produced."
        ),
        "transferability_warning": (
            "The manipulated class is whole-face GAN synthesis (StyleGAN), not face swapping. The "
            "Xception detector DeepTrace loads was trained on FaceForensics++ face-swap and "
            "reenactment forgeries, so this is a cross-generator generalisation test, not an "
            "in-distribution one. Performance on this StyleGAN corpus does not establish performance "
            "on face-swap or reenactment corpora and must not be quoted as a FaceForensics++ or "
            "Celeb-DF number. Use scripts/import_eval_set.py "
            "with a licensed copy of either corpus for an in-distribution figure."
        ),
        "independence_warning": (
            "Each file is a distinct face from a distinct source row, so unlike a locally-derived "
            "set these samples are independent and the Wilson intervals are not optimistic for that "
            "reason. They remain intervals over this sample of this corpus, not over all media."
        ),
        "scale_warning": scale_warning,
        "counts": {"real": len(real), "fake": len(fake),
                   "distinct_sources": len(real) + len(fake)},
        "licence_note": (
            f"Downloaded from {faces_meta['dataset_url']} (declared licence: {faces_meta['licence']}). "
            f"The media is not committed to this repository; data/benchmark/ is gitignored. "
            f"FaceForensics++ and Celeb-DF were deliberately not used: both require an accepted "
            f"end-user licence agreement from their authors."
        ),
        "ffmpeg_available": forensics.ffmpeg_available(),
        "source_media": [{
            "name": faces_meta["dataset"],
            "media_type": "image",
            "sha256": None,
            "note": f"Public corpus, {faces_meta['config']}/{faces_meta['split']} split, "
                    f"{faces_meta.get('rows_read')} row(s) read.",
        }],
        "items": items,
        "skipped": skipped,
    }


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch an openly-licensed representative face corpus for scripts/benchmark.py.")
    parser.add_argument("--faces", type=int, default=250,
                        help="Images per class for the manipulation set (default 250).")
    parser.add_argument("--pairs", type=int, default=200,
                        help="Total identity verification pairs, split evenly between "
                             "same-person and different-person (default 200).")
    parser.add_argument("--skip-faces", action="store_true",
                        help="Only fetch the identity pairs.")
    parser.add_argument("--skip-pairs", action="store_true",
                        help="Only fetch the manipulation set.")
    parser.add_argument("--clean", action="store_true",
                        help="Delete the existing dataset/ and pairs/ contents first.")
    args = parser.parse_args()

    if args.faces < 1 or args.pairs < 1:
        print("--faces and --pairs must be positive.")
        return REFUSED_EXIT

    real_dir = os.path.join(DATASET_DIR, "real")
    fake_dir = os.path.join(DATASET_DIR, "fake")

    if args.clean:
        # Scoped to the three generated locations, never to an operator path.
        for directory in (real_dir, fake_dir, PAIRS_DIR):
            shutil.rmtree(directory, ignore_errors=True)
        for path in (MANIFEST_PATH, PAIRS_CSV):
            try:
                os.remove(path)
            except OSError:
                pass
    elif not args.skip_faces and os.path.isdir(real_dir) and os.listdir(real_dir):
        print(f"{os.path.relpath(real_dir, REPO_ROOT)} already holds files. Re-run with --clean "
              f"to replace the set, or move the existing one aside.")
        return REFUSED_EXIT

    os.makedirs(DATASET_DIR, exist_ok=True)
    started = time.time()

    items: list[dict] = []
    skipped: list[dict] = []
    faces_meta: dict = {}
    if not args.skip_faces:
        items, skipped, faces_meta = fetch_faces(args.faces)
        if not items:
            print("\nNo face image could be downloaded. Nothing was written.")
            for entry in skipped[:5]:
                print(f"  {entry}")
            return NOTHING_DOWNLOADED_EXIT

    pairs_meta: dict | None = None
    if not args.skip_pairs:
        pair_rows, pair_skipped, pairs_meta = fetch_pairs(args.pairs)
        skipped.extend([{**entry, "stage": "identity_pairs"} for entry in pair_skipped])
        if not pair_rows:
            print("\nNo identity pair could be downloaded; identity metrics will report as "
                  "not measured rather than as zero.")
            pairs_meta = {**(pairs_meta or {}), "written": 0}

    if items:
        manifest = build_manifest(items, skipped, faces_meta, pairs_meta)
        with open(MANIFEST_PATH, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2)
        counts = manifest["counts"]
        print(f"\nWrote {counts['real']} authentic and {counts['fake']} synthesised face image(s).")
        print(f"Manifest: {os.path.relpath(MANIFEST_PATH, REPO_ROOT)}")
        if manifest["scale_warning"]:
            print(f"\nWARNING: {manifest['scale_warning']}")

    if pairs_meta and pairs_meta.get("same_person"):
        print(f"Wrote {pairs_meta['same_person']} same-person and "
              f"{pairs_meta['different_person']} different-person pair(s).")
        print(f"Pair list: {os.path.relpath(PAIRS_CSV, REPO_ROOT)}")

    if skipped:
        print(f"\n{len(skipped)} item(s) were skipped; the reasons are recorded in the manifest.")

    print(f"\nDone in {time.time() - started:.0f} s. This media is gitignored and is not "
          f"committed to the repository.")
    print("\nThe manipulated class is GAN face synthesis, not face swapping — a cross-generator "
          "test. Do not quote the result as a FaceForensics++ figure.")
    print("\nNext: backend/venv/Scripts/python.exe scripts/benchmark.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
