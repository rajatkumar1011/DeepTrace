# Validation

Everything in this file was measured on this project's own harnesses. No figure is
copied from a paper, carried over from another dataset, or estimated. Where a
result is poor it is reported as measured — the point of a validation document is
to be checkable, and a document that only contains good numbers is not.

Regenerate with:

```bash
backend/venv/Scripts/python scripts/benchmark.py
```

```bash
backend/venv/Scripts/python scripts/robustness.py --dataset-sample 16
```

**Use the backend's own interpreter, not whatever `python` resolves to.** On an
interpreter without `torch` installed, both harnesses complete in seconds and emit
a full, plausible set of metrics from their deterministic image-statistics
fallback. The output labels this — `environment.manipulation_model` reads
`Lightweight fallback`, a caveat says so, and `benchmark.py` now prints a banner
to stderr and exits `5` — but the figures look like results and must never be
quoted as detection performance. Every number in this document came from a run
where `environment.manipulation_model` was `DeepfakeBench Xception`.

The outputs (`data/benchmark/latest.json`, `data/benchmark/robustness.json`) are
gitignored, because they describe one operator's corpus on one machine. This
document quotes the run described below; the JSON is the authority.

| Run | Value |
|---|---|
| Accuracy harness | `scripts/benchmark.py`, 2026-08-26T15:04:02Z, 134.9 s |
| Robustness harness | `scripts/robustness.py`, 2026-08-26T14:09:23Z, 34.7 s |
| Python / platform | 3.11.9 / win32 |
| Manipulation model | DeepfakeBench Xception |
| Identity model | facenet-pytorch InceptionResnetV1 (vggface2), MTCNN detection |
| ffmpeg | 9.0-full_build (gyan.dev) |

The accuracy harness was run three times on the same corpus over 21 minutes, and
every figure in §2 and §3 below reproduced to the last decimal place — same
confusion matrix, same intervals, same AUC. Inference here is deterministic, so a
figure that moves between runs on unchanged input indicates a problem with the
run, not with the model. The only thing that changed across those runs was the
*wording* of the identity error definitions, which had been inheriting the
manipulation harness's phrasing; no number changed with it.

### Where these figures appear in the product

Not only here. Both surfaces read the same `latest.json` through one loader, so
neither can show a figure the other does not have:

| Surface | What it shows |
|---|---|
| `GET /api/benchmark` → **How it works** page | Both layers, with the confusion counts, the score distributions, the per-family split and the dataset revision |
| **Section 22 of every generated PDF report** | The same two layers, printed in the document an investigator actually receives |

Both report the identity layer *first* and the manipulation layer second, and both
print the failing figure rather than the flattering one. Neither presents a single
combined "accuracy": averaging a layer measured at AUC 0.996 with one measured at
AUC 0.417 would describe neither.

---

## 1. What the corpora are, and why these and not others

Both corpora are public, openly licensed, and downloaded by
`scripts/fetch_eval_data.py`. Neither is committed: `data/benchmark/` is
gitignored, so nothing here redistributes anyone's dataset.

| Purpose | Corpus | Split / revision | Read |
|---|---|---|---|
| Manipulation | [`TheKernel01/140k-Real-and-Fake-Faces`](https://huggingface.co/datasets/TheKernel01/140k-Real-and-Fake-Faces) (licence: `cc`) | `default/test`, rev `2abaf3c0` | 500 of 20 000 rows |
| Identity | [`logasja/lfw`](https://huggingface.co/datasets/logasja/lfw) — Labeled Faces in the Wild | `pairs/test`, rev `0ee47979` | 1200 of 2200 rows |

Labels are the source datasets' own, read from their `ClassLabel` names. Nothing
was inferred from directory placement, and no label was guessed.

**Three candidate corpora were deliberately rejected**, and the reasons matter as
much as the figures:

| Corpus | Why not |
|---|---|
| FaceForensics++, Celeb-DF | Both require a signed end-user licence agreement from their authors and are not redistributable. `scripts/import_eval_set.py` stages an operator's own licensed copy instead. |
| `nuriachandra/Deepfake-Eval-2024` | CC-BY-SA-4.0, but access-gated: the API returns HTTP 401. Bypassing an access control to obtain evaluation data would contradict the position this project takes on tracing. |
| `bitmind/popular-deepfakes` | MIT-licensed, but exposes only an `image` column with no label field. Labels would have had to be guessed, and a guessed label produces a fabricated metric. |

LFW lists its matched pairs before its mismatched ones, so the fetcher balances
per class explicitly. Taking the first *N* rows would have produced 200
same-person pairs and no different-person pairs, which leaves the false-match
rate — the number that matters most here — undefined.

---

## 2. Identity matching — the layer DeepTrace is actually built on

**n = 200 pairs (100 same-person, 100 different-person). 0 skipped.**
Cosine similarity of FaceNet embeddings at the application's own 0.60 threshold.

| Metric | Value | 95% CI (Wilson) | What it counts |
|---|---|---|---|
| Accuracy | 0.9150 | 0.8681 – 0.9463 | Pairs decided correctly. |
| Precision | **1.0000** | 0.9558 – 1.0000 | Of pairs called *same person*, the share that were. |
| Recall | 0.8300 | 0.7445 – 0.8911 | Of genuine same-person pairs, the share found. |
| F1 | 0.9071 | — | Harmonic mean of the two. |
| **False-positive rate** | **0.0000** | 0.0000 – 0.0370 | Two different people declared a match. |
| False-negative rate | 0.1700 | 0.1089 – 0.2555 | Same person missed. |
| ROC AUC | **0.9961** | — | Ranking quality, threshold-independent. |

Confusion matrix at 0.60: TP 83, FP **0**, TN 100, FN 17.

| Similarity | Same person | Different person |
|---|---|---|
| Mean | 0.7372 | 0.0445 |
| Median | 0.7774 | 0.0253 |
| Min – max | 0.0827 – 0.9407 | −0.3257 – 0.4653 |

The two distributions barely touch, which is what an AUC of 0.9961 means in
practice. **Zero false matches in 100 different-person pairs** is the figure with
the most direct consequence for a complainant: the error this system most needed
to avoid is the one where a stranger's face is declared to be theirs. The upper
confidence bound is 3.7% — a true rate above that is inconsistent with this
result, and 0/100 does not license a claim of zero in general.

The cost is on the other side: 17% of genuine matches are missed at this
threshold. That is the deliberate trade. Raising recall means lowering the
threshold, which buys false matches, and in an impersonation complaint a false
match is the more damaging error.

**Caveats carried in the harness output.** Pairs where no face could be detected
are skipped rather than counted as errors, which excludes exactly the hard cases;
these figures are therefore optimistic relative to uncontrolled media. LFW is
also mostly frontal, well-lit celebrity photography — easier than a screenshot
from a messaging app.

---

## 3. Manipulation detection — a measured generalisation failure

**n = 500 (250 authentic, 250 StyleGAN-synthesised). 0 skipped. Face detection
rate 100%.**

| Metric | Value | 95% CI (Wilson) |
|---|---|---|
| Accuracy | 0.4660 | 0.4227 – 0.5098 |
| Precision | 0.3607 | 0.2517 – 0.4861 |
| Recall | 0.0880 | 0.0588 – 0.1296 |
| F1 | 0.1415 | — |
| False-positive rate | 0.1560 | 0.1163 – 0.2061 |
| False-negative rate | 0.9120 | 0.8704 – 0.9412 |
| ROC AUC | **0.417** | — |

Confusion matrix at 0.50: TP 22, FP 39, TN 211, FN 228.

Per family, because recall and false-positive rate are different errors with
different consequences and averaging them hides both:

| Family | Class | n | Flagged | Metric | Value | 95% CI | Mean score |
|---|---|---|---|---|---|---|---|
| Real | authentic | 250 | 39 | false-positive rate | 0.1560 | 0.1163 – 0.2061 | 0.2835 |
| StyleGAN | manipulated | 250 | 22 | recall | 0.0880 | 0.0588 – 0.1296 | 0.2202 |

### What this result is

**A real cross-generator transferability failure, stated plainly.** An AUC of
0.417 is below 0.5, which means the ranking is *anti-correlated* with the truth on
this corpus: synthetic faces score slightly lower on average (0.2202) than real
ones (0.2835). No threshold rescues this. Moving the operating point trades one
error for the other and never produces a usable detector — the full threshold
sweep is in `latest.json` and shows exactly that.

### Why, and what it is not

- **It is not a broken evaluation.** The model loaded is the real DeepfakeBench
  Xception, not a stub — the harness records the active model name. Faces were
  found in 100% of files, so the detector received the input it expects. An
  earlier run of this harness produced similar numbers on media with almost no
  faces in it; that run *was* invalid, and this one is not.
- **It is not an in-distribution measurement.** Xception here was trained on
  FaceForensics++ face-swap and reenactment forgeries. The test class is
  whole-face StyleGAN synthesis: a fabricated identity, not a swapped face. The
  artefacts differ, and the model does not transfer to them.
- **It must not be quoted as a FaceForensics++ or Celeb-DF number.** It is a
  lower bound on face-swap performance, on a generator the model never saw. For
  an in-distribution figure, stage a licensed copy of either corpus with
  `scripts/import_eval_set.py --corpus-name "FaceForensics++ c23"` — the importer
  derives per-family breakdowns from the corpus's own directory structure.
- **Confounds were controlled.** Both classes are 256×256 aligned JPEG face
  crops from the same source dataset, so neither resolution, alignment nor codec
  correlates with the label. The only thing that differs is how the face was
  produced. Each file is a distinct face from a distinct source row, so the
  samples are independent and the Wilson intervals are not optimistic for that
  reason.

### Why this is reported rather than buried

This is the most useful validation result the project has, and the least
flattering. DeepTrace's stated position — in the UI, in the custody endpoint, in
every generated PDF — is that **no conclusion may rest on an AI manipulation
score alone.** That is normally an assertion a reviewer has to take on trust.
Here it is a measurement: on a generator this detector was not trained for, the
manipulation score carries no usable signal, and a system that had presented it
as a verdict would have been confidently wrong 91% of the time on the
manipulated class.

This is why the architecture puts the manipulation score behind identity
matching, hashing and custody rather than in front of them, why unavailable
modules are reported as unavailable instead of imputed to 0.5, and why the fused
risk score names its largest contributor and its excluded signals. A pipeline
whose weakest component is visible is auditable. One that hides it is not.

### A second corpus, for comparison

`data/benchmark/latest_localedits.json` holds a run over a small locally
constructed set (24 files: copy-move, splice, region recompression, face
smoothing, inpainting removal). AUC 0.3143 at n = 24 — same direction, intervals
far too wide to carry weight. It is reported for completeness, not as evidence.

---

## 4. Robustness to compressed, re-uploaded and screen-recorded media

Paired design: every file is scored by the real pipeline, then re-scored after a
real ffmpeg transform. **No labels are involved**, so nothing in this section is
an accuracy measurement — it measures *stability*, not correctness. The headline
is decision agreement: the share of pairs where the degraded copy lands on the
same side of the 0.50 threshold as the original.

Source: a balanced 16-file sample of the labelled accuracy corpus, plus 2
standalone audio files. Fingerprint `fd94fb0e10e752f6`.

### Visual channel — 80 paired comparisons

| Figure | Value | 95% CI |
|---|---|---|
| Decision agreement | **0.8750** | 0.7850 – 0.9307 |
| Decisions preserved | 70 / 80 | — |
| Mean absolute score change | 0.1151 | — |
| Borderline baselines excluded | 0 | — |

| Transform | Stands for | n | Agreement | Mean \|Δ\| | Max \|Δ\| | Signed drift |
|---|---|---|---|---|---|---|
| Screen recording | Filmed off a monitor, re-encoded | 16 | **1.0000** | 0.0839 | — | — |
| JPEG q75 | Ordinary recompression on save or upload | 16 | 0.8750 | 0.1167 | 0.4618 | raises |
| JPEG q40 | Heavy recompression, visible blocking | 16 | 0.8750 | 0.1324 | 0.2864 | raises |
| Messaging re-upload | 1024 px long edge, JPEG q65, metadata stripped | 16 | 0.8125 | 0.1195 | 0.3303 | raises |
| Double re-upload | Shared, saved, shared again | 16 | 0.8125 | 0.1229 | 0.3303 | raises |

**Every transform pushes the score up, never down** (`became_flagged` 2–3 per
transform, `became_cleared` 0 across all five). That direction is the important
finding: compression adds the same high-frequency artefacts the detector reads as
manipulation, so a re-shared authentic file drifts toward *false accusation*, not
toward being wrongly cleared. In a complaint workflow that is the dangerous
direction, and it is why the report states the media's compression history
alongside the score rather than presenting the score alone.

The screen-recording transform preserved 100% of decisions with the smallest mean
change of the five. Screen capture resamples and re-encodes but does not stack
JPEG quantisation on top of existing JPEG quantisation, which is what actually
moves this detector.

### Audio channel — 8 paired comparisons

| Figure | Value | 95% CI |
|---|---|---|
| Decision agreement | 0.3750 | 0.1368 – 0.6943 |

| Transform | n | Agreement |
|---|---|---|
| Narrowband 8 kHz | 2 | 1.0000 |
| MP3 96 kbps | 2 | 0.5000 |
| AAC 64 kbps | 2 | 0.0000 |
| Screen-recording audio | 2 | 0.0000 |

**Two files per transform. This figure is not usable and is published as a known
gap, not a result.** The 95% interval spans 0.14 – 0.69: it excludes almost
nothing. The harness also records a specific artefact — the audio editing
indicator derives a per-minute discontinuity rate, and on the two available clips
(both under 10 s) a single loudness transition saturates that term, so the deltas
partly measure short-clip extrapolation rather than the transform. Closing this
needs a real corpus of longer speech files. It is listed in the roadmap rather
than papered over.

### What the transforms do and do not reproduce

They reproduce what a transcoder does: resolution, frame rate, codec, bitrate,
metadata stripping, letterboxing. They do **not** reproduce monitor moiré, a
camera pointed at a screen, capture-card colour handling, or any specific
platform's proprietary encoder ladder. A transform that shifts every score by a
similar amount can leave agreement at 100% while still having moved the case away
from its true score, so mean signed delta is published alongside agreement rather
than hidden by it.

Decision agreement is measured against DeepTrace's own baseline for the original
file. **If that baseline is wrong, a preserved decision means the same wrong
answer survived the transform.** Given §3, that is not hypothetical on this
corpus. Read this section together with the labelled metrics, never instead of
them.

---

## 5. What hashing establishes, and what the analysis establishes

These are separate claims of different kinds, and the distinction is the reason
this system is more than a classifier with a UI. The application states the
boundary itself at
`GET /api/investigation/{id}/custody` — the same text appears in the UI and in
every generated PDF, and [WALKTHROUGH.md](WALKTHROUGH.md) quotes it verbatim from
a real case rather than paraphrasing it.

| Claim | Basis | Strength |
|---|---|---|
| The stored bytes are what was received | SHA-256 computed server-side during the write | **Arithmetic.** Verifiable by anyone with any SHA-256 implementation, without trusting DeepTrace. |
| This report describes those bytes | Digest recorded in the report and in the custody ledger | **Arithmetic.** |
| The face is consistent with the enrolled reference | FaceNet cosine similarity at 0.60 | **Evidence, with a measured false-match rate** (§2: 0/100, CI 0 – 3.7%). Not identification of a person. |
| The media shows signs of manipulation | Xception inference | **Evidence, with a measured error rate** (§3: on this corpus, no usable signal). Not proof. |
| A circulating copy is the same subject | Perceptual comparison of a retrieved copy | **Evidence about reach.** Not byte-identity, not an exhaustive search. |
| Who created the media | — | **Not established.** No module attributes content to a creator, account, device or tool. |
| That an offence occurred | — | **Not established.** For an investigator and a court. |

A hash is indifferent to content: a fabricated video hashes just as cleanly as a
genuine one. Integrity and authenticity are separate questions and only the first
is settled by hashing. Equally, an AI score says nothing about whether the file
has been altered since it arrived. Neither answers the other's question, which is
why the report keeps them in separate sections.

### The custody record's declared limits

The custody endpoint enumerates its own gaps rather than presenting itself as
complete — no identified custodian, no third-party (RFC 3161) timestamping,
digests stored in the same writable local database as the files they describe,
evidence served without authentication, a single local store, and reference media
retained but not hashed. Consequently:

- Altering a preserved file **is** detected. Altering the file *and* its stored
  digest together verifies clean. This was confirmed against a copy of the store,
  not assumed, and it bounds what any "verified" result here can mean.
- DeepTrace evidences the **file half** of a chain of custody. The custodial half
  — who held the media, on what authority, and every hand-off after export — is
  supplied by the investigating officer from their own case notes. The two
  together form the chain.
- **No claim of legal admissibility is made.** Admissibility is decided by a
  court under the applicable rules of evidence. A checksum supports an integrity
  argument; it does not create one.

---

## 6. Honest summary

| Layer | Status |
|---|---|
| Identity matching | **Validated and strong.** AUC 0.9961, precision 1.000, 0 false matches in 100 different-person pairs. |
| Hash chain and custody | **Arithmetic, independently verifiable, limits declared.** |
| Visual robustness | **Measured.** 87.5% decision agreement over 80 pairs; drift is toward false-positive, and that is stated. |
| Manipulation detection | **Measured and reported as failing to transfer** to StyleGAN synthesis (AUC 0.417). Needs an in-distribution corpus, which needs a licence. |
| Audio robustness | **Not usable at n = 8.** Published as a gap. |

Sample sizes are 500, 200, 80 and 8. Every interval quoted is a 95% Wilson
interval over *this sample of this corpus on this machine* — not over all media,
and not a general accuracy claim for DeepTrace or for any model it loads.

`GET /api/benchmark` reports `available: false` until an operator runs the
harness on their own machine. **DeepTrace ships no accuracy figures**, precisely
so that no number a reviewer sees is one nobody measured.
