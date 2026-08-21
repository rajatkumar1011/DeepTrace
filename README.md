# DeepTrace

DeepTrace is a hackathon prototype for digital impersonation analysis and forensic evidence preservation. It accepts image, video, and audio evidence, calculates integrity hashes, extracts media metadata and sampled frames, runs available pretrained analysis models, records an investigation timeline, and generates a forensic PDF report.

This repository is designed for local Windows development by a small team. It does not provide universal internet crawling, guaranteed identity, guaranteed attribution, 100% deepfake detection, or guaranteed criminal evidence.

## Repository Layout

```text
backend/                 FastAPI API, database models, services, requirements
frontend/                Next.js application and package-lock.json
data/demo/               Small demo assets such as lena.jpg

docs/                    Project documentation
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

No application secrets are required for the local demo. `.env.example` contains variable names only. The ML libraries recognize these optional cache variables:

- `HF_HOME`: Hugging Face cache directory
- `TORCH_HOME`: PyTorch checkpoint cache directory
- `TRANSFORMERS_CACHE`: Transformers cache directory
- `FFMPEG_PATH`: local FFmpeg path for team-machine documentation; the current service expects `ffmpeg` on `PATH`

Copy `.env.example` to `.env` only when a machine needs custom cache locations. Never add real credentials or tokens to Git.

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

The repository includes small demo assets:

- `data/demo/lena.jpg`: reference face image
- `data/test_video.mp4`: small suspicious-media demo video

Run both services, then:

1. Open the frontend.
2. Select **Protected Identity**.
3. Enter a name and upload `data/demo/lena.jpg`.
4. Select **New Investigation**.
5. Upload `data/test_video.mp4` and select the enrolled identity.
6. Click **Start Investigation**.
7. Open the generated Analysis view and click **Run Analysis**.
8. Review model names, frame-level outputs, metadata, evidence hashes, risk factors, and unavailable modules.
9. Open **Timeline**, **Evidence**, and **Similarity**.
10. Open **Report**, generate the PDF, and download it.

The demo video may not contain an identifiable face or audio stream. In that case, the corresponding module reports that the reference or media signal is unavailable. To demonstrate voice verification, enroll a reference WAV file and upload an audio/video file with a usable audio stream.

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
- Run `git status --short` and inspect the result.
- Do not commit from the demo machine unless the team explicitly agrees.
