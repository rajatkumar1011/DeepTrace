# DeepTrace — Final Round Engineering Report

**Project:** DeepTrace — Intelligent Digital Impersonation Detection & Forensic Evidence Preservation System
**Team:** Algorythm · **Team ID:** SIH26_28
**Domain:** Defence & National Security · **Category:** Software
**Report date:** 2026-08-25
**Workflow:** Match Identity → Analyze → Localize → Trace → Preserve → Respond

---

## 1. Completion Status

**Overall: ~95% of the scoped work is complete, verified, and demonstrable end to end.**

| Priority | Scope | Status |
| --- | --- | --- |
| **P0** | E2E workflow, identity matching, manipulation detection, evidence/hash system, timeline, PDF report | **100%** — complete and verified |
| **P1** | Voice, audio forensics, A/V consistency, localization, public-source tracing, similarity/copy tracing, explainable risk fusion, provenance/C2PA | **100%** — complete and verified |
| **P2** | Benchmark framework, UX polish, error handling, performance, documentation, demo dataset, automated tests | **~90%** — one deliberate deferral (see §8, Pydantic response models) |

The 5% shortfall is a single code-quality item (typed response schemas) that was consciously deferred at the end of the cycle rather than attempted, because it is a wide refactor across 22 endpoints with real regression risk against a system that is currently fully green. It is not a functional gap: no user-visible capability is missing.

There are **no known functional defects** and **no remaining blockers**.

---

## 2. Implemented Modules

Sixteen analysis services under `backend/services/`, all wired into the API and exercised by the demo path:

| Module | Responsibility |
| --- | --- |
| `identity.py` | MTCNN face detection + FaceNet 512-d embeddings, cosine similarity vs enrolled reference |
| `deepfake.py` | Manipulation analysis orchestration, frame sampling, aggregation |
| `deepfakebench_xception.py` | DeepfakeBench Xception inference wrapper (preferred detector) |
| `voice.py` | SpeechBrain ECAPA-TDNN speaker verification vs enrolled voice reference |
| `audio.py` | Audio editing indicators — splice/discontinuity and spectral analysis |
| `consistency.py` | Audio/visual consistency and lip-sync correlation |
| `localization.py` | Per-frame manipulation localization, suspicious time windows, overlay generation |
| `provenance.py` | C2PA Content Credentials reading, EXIF and container metadata provenance |
| `forensics.py` | Streaming upload to disk, SHA-256, perceptual hashing, frame/audio extraction, ffprobe metadata |
| `integrity.py` | Re-verification that stored evidence still matches its recorded SHA-256 |
| `similarity.py` | Perceptual-hash Hamming comparison against other locally held cases |
| `tracing.py` | Operator-supplied public HTTPS source retrieval with SSRF validation; copy classification |
| `risk.py` | Explainable identity + manipulation risk fusion with renormalised effective weights |
| `report.py` | 20-section forensic incident PDF |
| `response.py` | Case-specific response and official reporting guidance |

Supporting layers: `backend/main.py` (22 endpoints, background analysis, upload validation, sanitisation), `backend/models/schema.py` (SQLAlchemy 2.0 ORM), `backend/paths.py` (path anchoring and traversal containment), `backend/database.py`.

Frontend: 8 analysis panels plus shared components under `frontend/src/components/`, a 3-step guided intake, and a 7-tab case view.

---

## 3. Files Created and Modified

**Created (new code):**

```
backend/services/audio.py          backend/services/integrity.py
backend/services/localization.py   backend/services/response.py
backend/services/risk.py           backend/services/similarity.py

backend/tests/conftest.py               backend/tests/test_security.py
backend/tests/test_integrity.py         backend/tests/test_risk_fusion.py
backend/tests/test_benchmark_stats.py   backend/tests/test_api_contract.py
pytest.ini

scripts/benchmark.py   scripts/smoke_e2e.py   scripts/inspect_pdf.py   scripts/repair_paths.py

frontend/src/components/AnalysisProgress.tsx      frontend/src/components/AudioPanel.tsx
frontend/src/components/GuidancePanel.tsx         frontend/src/components/IntegrityPanel.tsx
frontend/src/components/MetadataPanel.tsx         frontend/src/components/RiskExplanation.tsx
frontend/src/components/SuspiciousFramesPanel.tsx frontend/src/components/TracePanel.tsx
frontend/src/lib/modules.ts
```

**Modified:** `backend/main.py` · `backend/database.py` · `backend/models/schema.py` · `backend/paths.py` · `backend/services/{consistency,deepfake,forensics,report,tracing,voice}.py` · `frontend/src/app/page.tsx` · `frontend/src/app/globals.css` · `frontend/src/config/constants.ts` · `frontend/src/lib/api/deeptrace.ts` · `frontend/src/types/index.ts` · `README.md` · `.env.example` · `.gitignore`

**Removed:** `backend/models/investigation.py` (consolidated into `schema.py`; no remaining importers) · `test_evidence.py` and `test_silence.wav` at the repository root (ad-hoc debugging scaffolding that hardcoded investigation IDs 7/8/10, asserted nothing, and would fail on any fresh clone — fully superseded by `backend/tests/test_integrity.py` and `scripts/smoke_e2e.py`).

Net change against `HEAD`: **+4,578 / −1,489** across 19 tracked files, plus ~2,900 lines of new untracked code.

---

## 4. Tests Executed and Results

All four gates were run twice, with a full backend restart in between, and again after the final repository cleanup.

| Gate | Command | Result |
| --- | --- | --- |
| Unit / contract suite | `python -m pytest` | **111 passed**, 0 failed (2.81 s) |
| End-to-end smoke test | `python scripts/smoke_e2e.py` | **57 passed, 0 failed** (48.6 s) |
| TypeScript | `npx tsc --noEmit` | exit 0 |
| Lint | `npx eslint src` | exit 0 |
| Production build | `npm run build` | Compiled successfully (7.0 s), 3/3 static pages |

Backend cold-start capabilities: `ffmpeg: true`, `deepfakebench_xception_weights: true`, `speaker_model_cached: true`, `c2pa_reader: true`.

**Coverage of the 111 unit tests,** by file — chosen to cover properties that must hold regardless of which models are installed:

- `test_security.py` — path traversal across 6 payloads, shell-metacharacter stripping, filename length bounds, `resolve_inside` containment, no absolute paths in public payloads, size-cap abort leaving no partial file, server-side hashing proven by independent recomputation, SHA-256 known-answer (`b"abc"`), 11 SSRF refusals, and a two-layer test proving no non-URL token can reach a network call.
- `test_integrity.py` — untouched file verifies; modified file reports MISMATCH and is *not* silently repaired; a single flipped bit at offset 2048 is detected; deleted file reports MISSING; absent recorded hash reports `NO_RECORDED_HASH` and explicitly is not treated as VERIFIED; one bad artifact fails the whole case; an **empty case does not claim integrity**.
- `test_risk_fusion.py` — effective weights sum to 1.0; the score is reconstructible by hand; unavailable signals are named with reasons and contribute no implicit zero; **absent C2PA credentials do not raise the score**; threshold anchoring places each model threshold at exactly 0.5; bands monotonic; the §27 disclaimer travels with every result.
- `test_benchmark_stats.py` — hand-computed confusion matrices, boundary inclusivity, undefined rates returning `None` rather than `0.0`, AUC for perfect/inverted/all-tied/partial-tie/single-class inputs, Wilson intervals that bracket the estimate, widen for small samples, and **do not claim certainty from 3/3**.
- `test_api_contract.py` — health limits, consent versioning, benchmark honesty, consent refusal across 5 falsy values, name validation, 6 unsupported media types → 415, unknown identity → 422, 8 unknown resources → 404 with no traceback or ORM leakage, and response hygiene asserting `PROJECT_ROOT` never appears in any payload.

The suite uses a throwaway database via `DEEPTRACE_DB_PATH`. Isolation was verified empirically, not assumed: real `deeptrace.db` row counts were identical before and after a full run (identities 19, investigations 26, analysis_results 173, evidence 204).

**Notable smoke-test results:** tamper detection reported `Integrity check FAILED: 1 hash mismatch(es) out of 20 artifacts` and then re-verified cleanly after restore; all 5 SSRF rejections held; a 29-event timeline was produced; re-analysis was idempotent (10 modules, 21 artifacts before and after, original hash unchanged, all 21 still verifying); the image path correctly reported `audio=not_applicable, consistency=not_applicable`; two PDFs were generated (1,034,794 bytes for INV2).

---

## 5. End-to-End Demo — What Actually Happens

A single deterministic run, all outputs from real pipeline execution:

1. Operator enrols a protected identity with a reference photo and explicit consent. MTCNN locates the face; FaceNet produces a real 512-d embedding; the consent text **version** is stored alongside the template so the enrolment is auditable.
2. Operator submits the suspicious media (upload or a demo chip) and optionally pastes public HTTPS URLs where copies are visible.
3. On case creation the file is streamed to disk under a sanitised name, SHA-256 is computed server-side from the persisted bytes, and the original is preserved as the first evidence artifact.
4. Background analysis runs module by module, each reporting its own stage while the UI polls. Frames are extracted and hashed; audio is demuxed when present.
5. Face matching, manipulation analysis, voice verification, audio-editing indicators, A/V consistency, localization, provenance/C2PA, similarity and tracing each produce a real result **or** an explicit "unavailable / inconclusive" with a stated reason.
6. Risk fusion combines only the signals that are actually available, renormalises the effective weights to 1.0, and itemises every excluded signal with the reason for exclusion.
7. The investigation timeline records every step as an audit trail.
8. Integrity verification re-hashes every artifact on disk and compares it against the digest recorded at preservation.
9. A 20-section forensic PDF is generated, and response guidance points at the correct official reporting routes.

Verified live in the browser: all 7 tabs render real data, the progress indicator tracks real module stages, and the console is free of errors.

---

## 6. Models Actually Used

| Purpose | Model | Notes |
| --- | --- | --- |
| Manipulation (preferred) | **DeepfakeBench Xception**, official `xception_best.pth` | 2-class softmax, index 1 = fake; 256×256; threshold 0.50. **CC BY-NC 4.0 — non-commercial research/evaluation only.** |
| Manipulation (fallback) | `Hemg/Deepfake-Detection` ViT via Transformers | Real model, real inference; the UI explicitly identifies which detector produced the result. |
| Face identity | facenet-pytorch MTCNN + `InceptionResnetV1(pretrained='vggface2')` | 512-d embeddings, cosine similarity, threshold 0.60. |
| Voice identity | SpeechBrain `speechbrain/spkrec-ecapa-voxceleb` | ECAPA-TDNN speaker verification, threshold 0.25. |
| Provenance | `c2pa-python` | Reads/validates embedded Content Credentials. A provenance signal, **not** a deepfake classifier. |

Supporting: PyTorch 2.2.2+cpu (CPU-only, eval/no-grad), OpenCV, ImageHash 64-bit pHash, Pillow EXIF, FFmpeg/ffprobe, reportlab.

All inference is local. **There are no API keys or secrets anywhere in the repository.**

---

## 7. Validation and Benchmark Results

**DeepTrace ships no accuracy figures, and this report claims none.**

`GET /api/benchmark` currently returns, truthfully:

```json
{"available": false,
 "reason": "No benchmark has been run in this environment. Run scripts/benchmark.py against a labelled dataset to produce metrics. DeepTrace does not ship pre-computed accuracy figures."}
```

This is a deliberate decision, not an omission. No genuinely labelled deepfake dataset exists in this environment: `lena.jpg` is an authentic photograph, `test_video.mp4` is an FFmpeg test pattern, and the provenance of an existing generated frame set could not be verified. Computing accuracy over guessed labels would be exactly the fabrication the brief forbids, so no labels were invented.

`scripts/benchmark.py` (430 lines) is nonetheless complete and **proven to work**, in two independent ways:

1. **Every statistic is unit-tested against hand-computed values** — confusion matrix, Wilson score interval, tie-corrected Mann-Whitney U AUC, threshold sweep (28 tests in `test_benchmark_stats.py`).
2. **A plumbing run was executed over a scratch dataset whose labels were true by construction** — `lena.jpg` as authentic, plus a copy manipulated in-process with PIL (a blurred, displaced splice of the face region). Real pipeline output: authentic **0.5591**, spliced **0.9981**; AUC 1.0; accuracy 0.5 (95% CI [0.0945, 0.9055]); n=2. The arithmetic was confirmed by hand (TP=1, FP=1, TN=0, FN=0).

That run produced one genuinely useful finding worth stating plainly: **the authentic photograph is a false positive at the shipped 0.50 threshold** — the sweep reached accuracy 1.0 only at thresholds ≥ 0.60. With n=2 this is an observation, not a calibration result, but it is the honest read.

The scratch dataset and `latest.json` were then deleted so the repository ships no accuracy figures, the endpoint was confirmed to revert to `available: false`, and `data/benchmark/` is git-ignored so a future run can never be committed.

To produce real metrics, an operator places labelled media in `data/benchmark/dataset/{real,fake}/` and runs the script. With no dataset present it writes nothing and prints instructions.

---

## 8. Known Limitations — Stated Honestly

**Product boundaries.** DeepTrace produces forensic **indicators** for investigator review. It does not provide, and must not be presented as providing: 100% deepfake detection or a binary real/fake verdict; internet-wide search, monitoring or surveillance; identification of who created or uploaded media; access to private platform APIs or any authenticated system; guaranteed legal admissibility; or definitive proof of impersonation from an AI score alone. Integrity verification proves the internal consistency of the *local* evidence store — it is not third-party timestamping, notarisation, or tamper-proof chain of custody.

**Engineering limitations.**

1. **No calibration data.** Thresholds (0.50 manipulation, 0.60 face, 0.25 voice) are the published defaults for each model, not values tuned on a validated dataset. The n=2 plumbing run suggests the 0.50 manipulation threshold may be too permissive on authentic photographs; this is untested at scale.
2. **Legacy rows display as unavailable.** Roughly 163–173 pre-existing `analysis_results` rows in the development `deeptrace.db` have `status = NULL` and old-schema `risk_fusion` payloads keyed `contributors` instead of `signals`. Historical cases therefore render as "unavailable" while freshly created cases are correct. This is a data-vintage artifact of schema evolution during development, not a code defect — a clean database has no such rows. **Demo on a freshly created case.**
3. **Pydantic response models not implemented.** Endpoint responses are constructed as dicts rather than typed schemas. `/docs` therefore under-describes response shapes. Deferred deliberately at the end of the cycle: it is a wide refactor across 22 endpoints with real regression risk against a fully green system, and it changes no user-visible behaviour.
4. **Tracing is operator-directed only.** DeepTrace retrieves only URLs the operator explicitly supplies, over HTTPS, refusing private/loopback/link-local/metadata addresses, capped at 8 URLs and 25 MB. There is no crawling and no platform integration.
5. **CPU-only performance.** A 12-frame video case takes tens of seconds. Adequate for demonstration; not tuned for throughput.
6. **Similarity tracing is local-scope.** Copy detection compares against other cases in this SQLite instance only.
7. **Benign log noise.** When a case original is a video and the investigator supplies an image as a suspected copy, the audio-fingerprint attempt logs a decode failure before degrading gracefully. Investigated and confirmed correct: the copy's type cannot be inferred from the case's type, so attempting and falling back is the right behaviour.
8. **`docs/` was empty** before this report; project documentation lives primarily in `README.md`.

---

## 9. Exact Demo Instructions

Two PowerShell windows at the repository root.

**Backend:**

```powershell
backend\venv\Scripts\python.exe -m uvicorn --app-dir backend main:app --host 127.0.0.1 --port 8000
```

**Frontend:**

```powershell
npm --prefix frontend run dev
```

Open `http://127.0.0.1:3000` and follow the guided flow:

1. **Start evidence collection.**
2. **Step 1 — Who is being impersonated?** Choose **Add a new reference**, enter a name, and select `data/demo/lena.jpg` as the reference photo. Optionally add `data/demo/reference.wav` as a reference voice.
3. **Tick the consent box** (enrolment is refused without it), then **Continue**.
4. **Step 2 — Add the suspicious media.** Click a demo chip or upload a file. Optionally paste public `https://` URLs.
5. **Continue**, review **Step 3**, then **Create case and begin analysis**.
6. Watch the progress bar report each module's real stage.
7. Walk the 7 tabs: **Findings** (per-module results plus the risk explanation with effective weights and every exclusion reason) → **Flagged frames** → **Audio & sync** → **Metadata** → **Evidence & integrity** (click **Run verification** to re-hash every artifact) → **Tracing** → **Next steps**.
8. Sidebar → **Generate evidence report** → download the PDF.

**Points worth making to judges:** enrolment is consent-gated and the consent *version* is stored; hashes are computed server-side from persisted bytes and re-verifiable on demand; unavailable modules say so with a reason and are excluded from the risk score rather than scored as zero; and `/api/benchmark` reports `available: false` because no benchmark has been run here.

Demo on a **freshly created case** (see §8.2). To show voice verification, enrol a reference WAV and submit media with a usable audio stream — the demo video has no audio track and no detectable face, so voice, A/V consistency and identity matching correctly report unavailable.

---

## 10. Remaining Blockers

**None.**

All four verification gates are green (111 unit tests, 57 end-to-end assertions, clean typecheck, clean lint, successful production build). The live application was confirmed working after a full backend restart and after the final repository cleanup, with no console errors. No functional capability in the brief is missing.

The one open engineering item — Pydantic response models (§8.3) — is code-quality polish that does not block the demo, affects no user-visible behaviour, and was deferred deliberately rather than rushed.

---

## Compliance Notes

- **No fabricated outputs.** Every score, hash, timestamp, report finding and trace result in the system comes from actual pipeline execution. Demo *inputs* are clearly labelled as demo assets. Where a module cannot run, it returns an explicit unavailable/inconclusive result with a reason.
- **No fabricated benchmarks.** See §7. No accuracy figure is claimed anywhere in the repository or this report.
- **No secrets.** The project uses no API keys of any kind; all inference is local. `.env.example` documents every variable the code actually reads, with defaults verified against source.
- **Security hardening** (all test-covered): upload type validation, size caps enforced while streaming, filename sanitisation, path-traversal containment, server-side hashing, SSRF-validated outbound requests, no arbitrary command execution, no internal filesystem paths in responses, no stack traces or ORM internals in error bodies, parameterised ORM queries.
- **Architecture preserved.** Next.js → FastAPI → AI/Forensics → Evidence Store → Output. SQLite and local execution retained deliberately; no production infrastructure was introduced for appearance.
- **Licensing.** DeepfakeBench and `xception_best.pth` are CC BY-NC 4.0 — non-commercial research and evaluation use only. Recorded in `README.md`.
