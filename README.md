# DeepTrace

DeepTrace is a hackathon prototype for digital impersonation analysis and forensic evidence preservation. It accepts image, video, and audio evidence, calculates integrity hashes, extracts media metadata and sampled frames, runs available pretrained analysis models, records an investigation timeline, and generates a forensic PDF report.

This repository is designed for local Windows development by a small team. It does not provide universal internet crawling, guaranteed identity, guaranteed attribution, 100% deepfake detection, or guaranteed criminal evidence.

## Who This Is For

**Primary user: the person being impersonated — the complainant.** DeepTrace is built
first for someone whose face or voice was misused. The guided flow is written in plain
language, with no forensic vocabulary to learn first, because a victim may be stressed
or unsure what to do next.

**Secondary user: the cybercrime investigator or forensic examiner who receives the
report.** The case view and the exported 23-section PDF are written for the officer
handling the complaint: full digests, per-module findings, the chain of custody, each
method used and the limits of each one, in the order an investigator needs them.

Reporting itself stays official. DeepTrace prepares the evidence package and points at
the correct route — it does not file anything on anyone's behalf.

## Measured Performance

| Layer | n | Precision | Recall | F1 | False-positive rate | ROC AUC |
|---|---|---|---|---|---|---|
| Identity matching (0.60) | 200 pairs | **1.0000** | 0.8300 | 0.9071 | **0.0000** [0–0.037] | 0.9961 |
| Manipulation detection (0.50) | 500 files | 0.3607 | 0.0880 | 0.1415 | 0.1560 | **0.417** |

Both figures are real, reproducible, and shown in the product — including the failing
one. See [Evaluation and Benchmarking](#evaluation-and-benchmarking) below, and
[docs/VALIDATION.md](docs/VALIDATION.md) for the method, corpora and caveats.

## Repository Layout

```text
backend/                 FastAPI API, database models, services, requirements
backend/services/        Analysis modules (identity, deepfake, voice, audio, localization,
                         provenance, similarity, tracing, integrity, risk, report, response)
backend/tests/           pytest suite (deterministic logic, security boundaries, API contracts)
frontend/                Next.js application and package-lock.json
scripts/                 benchmark.py, robustness.py, fetch_eval_data.py, walkthrough.py,
                         smoke_e2e.py, and local maintenance utilities
data/demo/               Small demo assets such as lena.jpg
data/benchmark/          Evaluation corpora and their results (both git-ignored)
docs/                    VALIDATION.md (measured figures), WALKTHROUGH.md (one full
                         investigation), ENGINEERING_REPORT.md
```

Runtime databases, uploads, extracted evidence, generated reports, model caches, virtual environments, and `node_modules` are intentionally local and ignored by Git.

## Prerequisites

- Windows 10 or Windows 11
- Python 3.11 (64-bit)
- Node.js 20 LTS or newer LTS release
- npm 10 or newer
- FFmpeg available on `PATH`
- Internet access on first model use to download pretrained checkpoints from Hugging Face and the FaceNet checkpoint source
- Enough disk space for pretrained checkpoints; CPU inference works but can be slow

Check the tools:

```powershell
python --version
node --version
npm --version
ffmpeg -version
```

The verified development environment uses Python 3.11, Node.js with Next.js 16.3.1, and CPU PyTorch.

## Backend Setup

Open PowerShell at the repository root:

```powershell
py -3.11 -m venv backend\venv
backend\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt
```

The requirements file uses the official PyTorch CPU wheel index and pins matching versions:

- `torch==2.2.2+cpu`
- `torchvision==0.17.2+cpu`
- `torchaudio==2.2.2+cpu`
- `facenet-pytorch==2.6.0`
- `transformers==4.41.2`
- `SpeechBrain==1.0.3`

Verify the ML stack:

```powershell
backend\venv\Scripts\python.exe -c "import torch, torchvision, torchaudio; print(torch.__version__, torchvision.__version__, torchaudio.__version__)"
backend\venv\Scripts\python.exe -c "from facenet_pytorch import MTCNN, InceptionResnetV1; print('FACENET OK')"
```

### Database migration (run once after pulling)

The submitter-identification feature adds a `case_submitters` table and an
`investigations.submitter_id` column. Apply it once:

```powershell
backend\venv\Scripts\python.exe backend\migrations\001_add_case_submitter.py
```

Expected output: `DeepTrace migration complete: case_submitters + investigations.submitter_id are ready.`
The migration is additive and idempotent. Existing investigations are preserved; cases
created before this change simply carry `submitter_id = NULL`.

Start the backend:

```powershell
backend\venv\Scripts\python.exe -m uvicorn --app-dir backend main:app --host 127.0.0.1 --port 8000
```
The API is available at `http://127.0.0.1:8000` and interactive API docs are at `http://127.0.0.1:8000/docs`.

The first use of identity, deepfake, or voice analysis may download model files. On Windows, SpeechBrain uses a copy strategy to avoid requiring symlink privileges. Do not commit downloaded checkpoints.

## Frontend Setup

In a second PowerShell window at the repository root:

```powershell
npm --prefix frontend ci
npm --prefix frontend run dev
```

Open `http://127.0.0.1:3000`.

`frontend/package-lock.json` is committed and should be used with `npm ci` for reproducible frontend installs. Do not use `npm install` to rewrite the lockfile unless dependencies intentionally change.

For a production build:

```powershell
npm --prefix frontend run build
npm --prefix frontend start
```

## Environment Variables

No application secrets are required, and DeepTrace uses no API keys of any kind — all
analysis runs locally on CPU. `.env.example` documents every variable the code actually
reads, with its default; copy it to `.env` only if you need to change one.

Backend behaviour:

- `DEEPTRACE_DB_PATH`: SQLite file (default: `deeptrace.db` at the repository root)
- `DEEPTRACE_MAX_UPLOAD_MB`: suspicious-media size cap (default `200`)
- `DEEPTRACE_MAX_REFERENCE_MB`: reference image/audio size cap (default `25`)
- `DEEPTRACE_FRAME_SAMPLES`: frames sampled per video (default `12`)
- `DEEPTRACE_CORS_ORIGINS`: comma-separated allowed origins (default `http://localhost:3000,http://127.0.0.1:3000`)

Tooling and caches:

- `FFMPEG_PATH`: absolute path to `ffmpeg`; blank uses `PATH`
- `HF_HOME`, `TORCH_HOME`, `TRANSFORMERS_CACHE`: model cache locations

Frontend (`frontend/.env.local`):

- `NEXT_PUBLIC_API_BASE_URL`: backend origin (default `http://localhost:8000`)

Never add real credentials or tokens to Git.

## ML Model Setup

DeepTrace uses these pretrained models when they load successfully:

- Face identity: `facenet-pytorch` MTCNN plus `InceptionResnetV1(pretrained='vggface2')`; output is a real 512-dimensional FaceNet embedding.
- Manipulation analysis: `Hemg/Deepfake-Detection` through Transformers; sampled frames are analyzed individually and aggregated.
- Manipulation analysis (preferred when the local checkpoint is present): DeepfakeBench Xception using the official `xception_best.pth` release. This detector and checkpoint are CC BY-NC 4.0 and are limited to non-commercial research/evaluation use.
- Voice identity: SpeechBrain `speechbrain/spkrec-ecapa-voxceleb`; reference and suspicious audio are compared with the real ECAPA speaker-verification model.
- Content provenance: `c2pa-python` reads and validates embedded C2PA Content Credentials when supported media includes them. This is a provenance signal, not a deepfake classifier.

Models are loaded lazily, one analysis family at a time, and inference runs with evaluation/no-gradient mode. CPU inference is supported. If a model cannot load, the UI marks that module unavailable or explicitly identifies the lightweight fallback; it does not fabricate scores.

### DeepfakeBench Xception checkpoint

The local development setup can use the official DeepfakeBench v1.0.1
`xception_best.pth` checkpoint. It is downloaded to an ignored local folder and
is selected before the Hugging Face detector:

```powershell
New-Item -ItemType Directory -Force backend\pretrained_models\deepfakebench
Invoke-WebRequest `
  https://github.com/SCLBD/DeepfakeBench/releases/download/v1.0.1/xception_best.pth `
  -OutFile backend\pretrained_models\deepfakebench\xception_best.pth
```

DeepfakeBench and this checkpoint are CC BY-NC 4.0. Use them only for
non-commercial research/evaluation unless you obtain separate permission.

## Demo Workflow

The repository includes small demo assets, offered in the UI as one-click chips so the
demo needs no local media:

- `data/demo/lena.jpg`: reference face image
- `data/demo/reference.wav`, `data/demo/suspicious_audio.wav`: reference and suspicious audio
- `data/test_video.mp4`: suspicious-media demo video

Run both services, open `http://127.0.0.1:3000`, then:

1. Click **Start evidence collection**. The intake is four steps: **Identification →
   Reference identity → Suspicious media → Review & begin**.
2. **Step 1 — Identification.** Enter the complainant's name, Aadhaar number, gender,
   date of birth and mobile number. These are **self-declared identification details
   only.** DeepTrace validates their *format* — 12 Aadhaar digits, a valid 10-digit
   Indian mobile, a date of birth that is not in the future — and nothing else. It does
   **not** authenticate Aadhaar against UIDAI, confirm phone ownership, or establish
   legal identity, and it makes no such claim anywhere in the product or the report.
   The values are stored in the local SQLite database, are never returned to the client
   after submission, and are not printed into the PDF.
3. **Step 2 — Who is being impersonated?** Choose an existing protected identity, or
   **Add a new one** and supply a name plus a reference photo (`data/demo/lena.jpg`).
   Optionally add a reference voice sample.
4. Tick the consent box. Enrolment is refused without it: biometric templates are only
   stored with recorded consent, and the consent text version is stored alongside them.
   Choosing **Continue without identity comparison** skips enrolment entirely — the file
   is still preserved and the other forensic checks still run.
5. Click **Continue**.
6. **Step 3 — Add the suspicious media.** Upload a file or click a demo chip.
7. Optionally paste public `https://` URLs where copies are visible. DeepTrace retrieves
   only what you point it at, over HTTPS, refusing private and loopback addresses.
8. Click **Continue**, review **Step 4**, then click **Create case and begin analysis**.
9. Watch the progress bar. Each module reports its own stage; analysis runs in the
   background and the page polls for updates.
10. **Findings** tab: plain-language per-module results, and the risk explanation showing
    each signal's effective weight plus every excluded signal and the reason it was excluded.
11. **Flagged frames**: suspicious time windows and the localization overlays.
12. **Audio & sync**: voice comparison, audio editing indicators, A/V consistency.
13. **Metadata**: container/codec metadata and C2PA Content Credentials.
14. **Evidence & integrity**: the preserved artifact list. Click **Run verification** to
    re-hash every file on disk and compare it against the digest recorded at preservation.
15. **Tracing**: results for any URLs supplied, plus similar media held in other local cases.
16. **Next steps**: case-specific guidance, the evidence package to attach, and official
    reporting routes.
17. In the sidebar, click **Generate evidence report** and download the PDF.

A module reports itself unavailable when its input is genuinely missing — for example the
demo video has no audio track and no detectable face, so voice, A/V consistency and
identity matching all report unavailable with a stated reason. That is the intended
behaviour: an unavailable module is neither evidence of authenticity nor of manipulation,
and it is excluded from the risk score rather than scored as zero. To demonstrate voice
verification, enrol a reference WAV and submit media with a usable audio stream.

## Tests

```powershell
backend\venv\Scripts\python.exe -m pytest
```

The suite covers deterministic logic and boundaries that must hold regardless of which
models are installed: filename sanitisation and path traversal, upload size caps,
server-side hashing, SSRF URL validation, evidence tamper detection, risk-fusion
arithmetic and exclusion honesty, benchmark statistics, and API validation/error paths.
It uses a throwaway database via `DEEPTRACE_DB_PATH` and never touches real case data.

The model-backed happy path is covered separately, against a running server:

```powershell
backend\venv\Scripts\python.exe scripts\smoke_e2e.py
```

## Evaluation and Benchmarking

The repository ships **no accuracy figures**, so `GET /api/benchmark` reports
`available: false` on a fresh clone. Figures come from running the harnesses here.

**Measured on this project's own harnesses** — full method, corpora, provenance and
caveats in **[docs/VALIDATION.md](docs/VALIDATION.md)**, and one complete
investigation from upload to final report in
**[docs/WALKTHROUGH.md](docs/WALKTHROUGH.md)**:

| Layer | n | Precision | Recall | F1 | False-positive rate | ROC AUC |
|---|---|---|---|---|---|---|
| **Identity matching** (0.60) | 200 pairs | **1.0000** | 0.8300 | 0.9071 | **0.0000** [0–0.037] | 0.9961 |
| **Manipulation detection** (0.50) | 500 files | 0.3607 | 0.0880 | 0.1415 | 0.1560 [0.116–0.206] | **0.417** |

Robustness under real ffmpeg degradation (compression, messaging re-upload,
screen-recording): visual decision agreement **0.8750** over 80 paired comparisons;
audio **0.3750** over 8, published as a gap.

Read the two rows together. Identity matching — the layer DeepTrace is actually
built on — did not once mistake a stranger for the reference person on this sample.
Manipulation detection scored **below the 0.5 chance line** on whole-face StyleGAN
synthesis: the Xception detector was trained on face-swap artifacts and does not
transfer, so on that corpus it ranked generated faces *below* authentic ones. That
figure is published, shown in the UI and printed in every PDF report, because it is
the measured reason for the rule the product already follows: **no conclusion rests
on a manipulation score alone.**

### Reproducing it

Fetch the corpora (published datasets at pinned revisions — nothing is scraped and
no label is invented), then run the harnesses:

```powershell
backend\venv\Scripts\python.exe scripts\fetch_eval_data.py
```

```powershell
backend\venv\Scripts\python.exe scripts\benchmark.py
```

```powershell
backend\venv\Scripts\python.exe scripts\robustness.py --dataset-sample 16
```

**Use `backend\venv\Scripts\python.exe`, not bare `python`.** On an interpreter
without `torch`, both harnesses complete in seconds and emit a full, plausible set
of metrics from a deterministic image-statistics fallback. `benchmark.py` prints a
banner to stderr and exits `5` rather than let that pass as a measurement.

To evaluate your own media instead, place authentic files in
`data/benchmark/dataset/real/` and manipulated files in `data/benchmark/dataset/fake/`,
and optionally add `data/benchmark/identity_pairs.csv`
(`image_a,image_b,same_person`, paths relative to `data/benchmark/pairs/`). With no
dataset present the script writes nothing and prints instructions, so the API keeps
honestly reporting that no benchmark has been run.

Results are written to `data/benchmark/latest.json`: the confusion matrix at the
operating threshold, accuracy with a 95% Wilson confidence interval, precision,
recall, specificity, F1, ROC AUC, a threshold sweep, per-class score distributions,
a per-family breakdown, the face-detection rate, the dataset revision, and a
fingerprint of the evaluated file set. Every figure comes from running the real
pipeline on those files. Both the dataset and the results are git-ignored.

## What DeepTrace Does Not Claim

DeepTrace presents forensic **indicators** for investigator review. It does not claim, and
must not be presented as providing:

- 100% deepfake detection, or a binary real/fake verdict
- internet-wide search, monitoring or surveillance
- identification of who created or uploaded the media
- access to private platform APIs or any authenticated system
- guaranteed legal admissibility of the preserved evidence
- definitive proof of impersonation from an AI score alone
- **verification of a submitter's identity.** The identification details collected at
  intake are self-declared. Their format is validated; nothing is checked against UIDAI,
  a telecom operator, or any other authority. A recorded Aadhaar number establishes that
  someone typed twelve digits, not who filed the case.

Integrity verification proves the internal consistency of the local evidence store. It
does not provide third-party timestamping, notarisation or tamper-proof custody. Reporting
remains an official process performed by the user or an authorised investigator; DeepTrace
prepares the evidence package and points to the correct routes.

## Troubleshooting

### Torch fails to import

Use the repository virtual environment and reinstall the pinned CPU stack:

```powershell
backend\venv\Scripts\python.exe -m pip uninstall -y torch torchvision torchaudio
backend\venv\Scripts\python.exe -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.2.2+cpu torchvision==0.17.2+cpu torchaudio==2.2.2+cpu
```

Do not install CUDA wheels for the default hackathon setup.

### Model download fails

Check internet access, disk space, and the Hugging Face cache location. Retry the model operation after removing only the incomplete cache directory. Do not delete the project database or evidence directories.

### SpeechBrain reports a symlink privilege error

The service uses SpeechBrain's copy strategy on Windows. Ensure `SpeechBrain==1.0.3` is installed from `backend/requirements.txt` and that the model cache directory is writable.

### FFmpeg or audio extraction fails

Install a Windows FFmpeg build and add its `bin` directory to `PATH`. Open a new PowerShell window and confirm `ffmpeg -version` works. The voice module correctly reports unavailable when no reference voice or extractable audio exists.

### Frontend cannot reach the API

Confirm the backend is running on port 8000 and the frontend is running on port 3000. The configured development CORS origins are `localhost:3000` and `127.0.0.1:3000`.

### A report or database path looks inconsistent

Always launch the backend with `--app-dir backend` from the repository root. The SQLite database is anchored at the repository root so different working directories use the same file.

## Sharing Checklist

Before pushing to GitHub:

- Keep `backend/requirements.txt` and `frontend/package-lock.json` tracked.
- Keep `data/demo/` demo inputs tracked if they are approved for sharing.
- Do not commit `backend/venv`, `frontend/node_modules`, `.next`, databases, uploads, evidence, reports, pretrained model files, caches, `.env`, or secrets.
- Do not commit `data/benchmark/` contents. Evaluation media and metrics are specific to one operator and one machine; committing `latest.json` would ship accuracy figures that do not describe anyone else's environment.
- Run `git status --short` and inspect the result.
- Do not commit from the demo machine unless the team explicitly agrees.
