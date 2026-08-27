# One complete investigation, end to end

Case **#34**, produced by `scripts/walkthrough.py` against `http://127.0.0.1:8000` on 2026-08-26 14:34:44.

Every number, hash and finding below was read back from the API after the run. Nothing here is transcribed by hand or written for illustration. Re-running the script produces a new case with its own values; the ones printed here belong to this one.

## Who this is for

**Primary user: the person being impersonated — the complainant.** They arrive with a link or a file and one question: *what do I do about this?* The output they need is a document they can hand to someone with authority to act.

**Secondary user: the cybercrime investigator or forensic examiner** who receives that document. They need to know what was preserved, when, how it was measured, and what the measurement does not establish.

**Neither of them gets a verdict.** DeepTrace does not decide whether media is genuine or fake. It measures, records and hands over.

## Stage 1 — What was submitted

_Demonstration input: two different genuine photographs of the same person, taken from the public Labeled Faces in the Wild corpus. This exercises the impersonation path the product is actually built for — a real face surfacing somewhere the complainant did not put it — with input whose ground truth is known, so the identity result can be checked rather than merely read. The media is demonstration data; every score, hash, timestamp and finding below is real output from this run._

| Field | Value |
|---|---|
| Suspicious media | `lfw_test_00000_b.jpg` |
| Reference photograph | `lfw_test_00000_a.jpg` |
| Protected identity | #24 — consent recorded at enrolment |
| Declared source URLs | `https://vis-www.cs.umass.edu/lfw/` |
| Stored filename | `lfw_test_00000_b.jpg` |
| Media type | `image` |
| Size on disk | `10073 bytes` |


## Stage 2 — Preservation, and exactly what it proves

The API hashes the upload **server-side on receipt**. No client-supplied hash is trusted. To make this section independent of the system it is describing, `walkthrough.py` recomputed the digest of the file it sent, in its own process, and compared:

| Digest | Value |
|---|---|
| SHA-256 recorded by the API | `325a8187df27cc01…879e9da6` |
| SHA-256 recomputed by this script | `325a8187df27cc01…879e9da6` |
| Agreement | **identical** |


### What the hash proves

Quoted from `GET /api/investigation/34/custody` — the same text the application shows the user and prints in the PDF, not a paraphrase written for this document:

- **The stored file is byte-for-byte what DeepTrace received** — The digest is computed while the upload is being written to disk, over the same byte stream that lands in the evidence store. It therefore belongs to the bytes DeepTrace actually holds — not to a second, separate read, and not to any value the uploader supplied. Client-submitted hashes are never accepted.
- **Change to a preserved file is detectable, as long as the record is untouched** — Re-reading a file and re-hashing it reproduces the recorded digest exactly if nothing changed, and altering a single bit produces an entirely different digest. This reliably catches storage corruption, truncated or failed transfers, re-encoding, re-saving through an editor, accidental overwriting, and modification by anyone who can reach the evidence file but not this database. It does not catch someone who changes both.
- **Two files are, or are not, the same file** — Identical digests mean identical bytes. This is what links the media you submitted to the copy described in the report, and to any traced copy that turns out to be the same file rather than merely a similar one.
- **Which exact file each finding refers to** — Every analysis result is attached to a case whose original file has a recorded digest, so a finding cannot later be re-pointed at a different file without the mismatch showing.


### What the hash does not prove

- **Not who created, uploaded or handled the file** — DeepTrace records no operator, custodian or account identity. It runs as a single-operator local tool, so the custody record describes what happened to the file, never who did it.
- **Not when the content was originally made** — The recorded time is when DeepTrace received the file, taken from this machine's clock. There is no third-party timestamp authority countersignature (RFC 3161), so the time is a local assertion.
- **Not whether the content is authentic or manipulated** — A hash is indifferent to what a file depicts. A fabricated video hashes just as cleanly as a genuine one. Integrity and authenticity are separate questions, and only the first is settled by hashing.
- **Not tamper-proof, and not fully tamper-evident either** — SHA-256 is a detection primitive, not a protection primitive. The digest is stored in the same local database that the same person can edit, and it is not signed, hash-chained, or held anywhere independent of the file it describes. Changing a preserved file alone is detected; changing the file and its recorded digest together is not. Verification is therefore a consistency check between two artifacts under common control, not a guarantee against a determined local operator.
- **Nothing about the file before DeepTrace received it** — The digest begins at the moment the bytes entered DeepTrace's write loop. It says nothing about whether the media was edited, re-encoded or re-uploaded before it was submitted, or about where it had been until then.
- **Not legal admissibility** — Admissibility is decided by a court under the applicable rules of evidence, on the record before it. A checksum supports an integrity argument; it does not by itself make evidence admissible.


### Re-verification on demand

`GET /api/investigation/34/verify` re-reads every preserved artifact from disk and re-hashes it (HTTP 200):

| Field | Value |
|---|---|
| `artifacts_checked` | `2` |
| `chain_intact` | `True` |
| `verified_at` | `2026-08-26T14:35:31+00:00` |
| `algorithm` | `SHA-256` |
| `summary` | All 2 preserved artifact(s) re-hash to their recorded SHA-256 values. The evidence set is intact. |


**The endpoint states its own limits:** This verifies internal consistency of the local evidence store. It does not provide third-party timestamping, notarisation or tamper-proof custody, and does not by itself establish legal admissibility.

## Stage 3 — Chain of custody

> SHA-256 hashing establishes that the preserved files have not changed since DeepTrace received them. The AI analysis estimates how likely the content is manipulated, and how closely it resembles an enrolled reference. Neither answers the other's question, and the report keeps them in separate sections for that reason.

**What this record is, in the endpoint's own words:** DeepTrace evidences the file half of the chain and records no custodian, so this is a file-integrity record rather than a complete chain of custody. The investigating officer supplies the custodial half from their own case notes; the two together form the chain.

_A complete chain of custody records four things about an item of evidence: what it is, who held it, when it passed from one holder to the next, and under what authority._

**DeepTrace supplies:**

- What the item is — the exact bytes received, identified by a digest computed as they were written to disk.
- What was produced from it — every frame, audio track and overlay the pipeline derived, each with its own digest.
- When each of those things was recorded, in sequence, by this machine's clock.
- Whether the preserved files still match the digests recorded for them.

**The investigator supplies:**

- Who held the media before it was submitted to DeepTrace, and how they obtained it.
- Who operated DeepTrace, on what authority, and who has had access to this machine.
- Every hand-off of the exported report and evidence package after it leaves DeepTrace.
- Any external timestamping, sealing or notarisation the case requires.

| Field | Value |
|---|---|
| Artifacts in the ledger | `2` |
| Acquired (received, never regenerated) | `2` |
| Derived (recomputed on re-analysis) | `0` |
| Artifacts with no digest | `0` |
| Chronology entries | `20` |


### Artifact ledger

| Artifact | Origin | Role | Preserved (UTC) | Digest |
|---|---|---|---|---|
| `original` | `acquired` | Root of the chain — acquired | `2026-08-26 14:34:44` | `325a8187df27cc01…879e9da6` |
| `traced_copy` | `acquired` | Separately acquired copy | `2026-08-26 14:35:31` | `59024b3464a0defd…75538005` |


_Lineage is recorded by the pipeline stage that produced each artifact. DeepTrace does not store an explicit parent reference on individual files, so the relationships below reflect how each stage operates rather than a per-file pointer._

### Chronology

Recorded as each action happened, not reconstructed afterwards. 20 entries; the first and last few:

| # | Event | Recorded (UTC) | Description |
|---|---|---|---|
| `1` | `investigation_created` | `2026-08-26 14:34:44` | Investigation opened for lfw_test_00000_b.jpg (image). |
| `2` | `evidence_uploaded` | `2026-08-26 14:34:44` | Original media preserved: lfw_test_00000_b.jpg, 10073 bytes. |
| `3` | `hash_generated` | `2026-08-26 14:34:44` | SHA-256 computed server-side during write: 325a8187df27cc01af2569205ea278ac5ebdcadc0bee83311484c2ef879e9da6 |
| `4` | `identity_attached` | `2026-08-26 14:34:44` | Case linked to protected identity: Walkthrough Subject (demonstration). |
| `5` | `source_recorded` | `2026-08-26 14:34:44` | 1 source URL(s) recorded at intake. |
| `6` | `analysis_started` | `2026-08-26 14:34:44` | Full analysis pipeline started. |
| `…` | `…` | `…` | … |
| `17` | `analysis_completed` | `2026-08-26 14:35:28` | Full analysis pipeline completed. |
| `18` | `source_trace_failed` | `2026-08-26 14:35:31` | Could not retrieve https://vis-www.cs.umass.edu/lfw/: Host could not be resolved (getaddrinfo failed). |
| `19` | `source_traced` | `2026-08-26 14:35:31` | Investigator-supplied copy compared: High similarity (Perceptual hash agreement is 100.0% (visual similarity,  |
| `20` | `integrity_verified` | `2026-08-26 14:35:31` | Integrity re-verification: All 2 preserved artifact(s) re-hash to their recorded SHA-256 values. The evidence  |


_Case events are written as they happen and read back in the order they were written. The table is ordinary storage, so this is a record kept in sequence — not an append-only or cryptographically chained log. Each event is committed on its own, so a stage that records an action and then fails can leave a claim standing that nothing later contradicts. Running an integrity re-verification also appends an event, which is why simply viewing this custody record does not._

### Gaps the record declares about itself

- **No identified custodian** — No table in DeepTrace records an operator, account or session, and there is no authentication layer that could establish one. The chain covers the handling of files, not the people who handled them, and there is no hand-off, access or export log. An investigator relying on this record supplies the custodial half from their own case notes.
- **No third-party timestamping** — Times are taken from the local system clock. There is no RFC 3161 timestamp authority, cryptographic signature, notarisation or external witness, so the chronology is entirely self-recorded.
- **Verification cannot detect a change made to both file and record** — The recorded digest sits in the same writable local database as the file it describes, and is not signed or chained. Altering a preserved file is detected; altering the file and its stored digest together verifies clean. This has been confirmed against a copy of the store rather than assumed, and it bounds what any 'verified' result here can mean.
- **Evidence files are served without authentication** — Preserved originals and derived frames are exposed by the local server as static files, with no credential required and no read-only or write-once protection applied after hashing. DeepTrace is intended to run on a single trusted machine, and offers no protection if it does not.
- **Single local store** — The custody record lives in this machine's database and evidence folder. There is no off-machine replica and no write-once medium, so it inherits the durability of the host it runs on.
- **Reference media is stored but not hashed** — The enrolled reference image and voice sample for the protected identity are retained with a recorded consent decision, but DeepTrace does not compute a digest for them. Integrity claims in this record cover the submitted media and its derived artifacts only.


These are stated rather than hidden, and they are the reason this project does not claim guaranteed legal admissibility. A custody record that presents itself as complete when it is not is worse than one that names its own limits.

**Preserved artifacts: 2.** `GET /api/investigation/34/evidence` lists each with its own digest.

**Timeline events: 20**, from `GET /api/investigation/34/timeline`.

## Stage 4 — Analysis, and exactly what it establishes

Pipeline wall-clock: **46.3 s**. Final case status: `completed`.

| Module | Status | Score | Confidence | What it concluded |
|---|---|---|---|---|
| `metadata` | `completed` | _none_ | — | Metadata is a provenance signal only. Absent, generic or rewritten metadata is common in re-encoded and re-shared media and does not by itself indicate manipulation; present metadata does not establish authenticity. |
| `audio` | `not_applicable` | _none_ | — | The submitted media is a still image and carries no audio stream. |
| `deepfake` | `completed` | 0.4225 | 0.16 | Face-manipulation detector trained on cropped faces. Treat the output as a forensic indicator, not proof. |
| `localization` | `completed` | _none_ | — | Timestamps mark sampled frames whose manipulation score crossed the threshold; unsampled frames between them were not examined. Overlay images visualise high-frequency residual energy — where blending and re-compression artefacts concentrate — and are an explainable forensic aid, not a trained segmentation mask. |
| `identity` | `completed` | 0.8766 | 0.88 | Best similarity 0.877 is above the 0.60 same-person threshold for VGGFace2 embeddings, consistent with the media depicting Walkthrough Subject (demonstration). |
| `voice` | `unavailable` | _none_ | — | The submitted media contains no decodable audio track, so no voice could be compared. |
| `consistency` | `not_applicable` | _none_ | — | Reported `not_applicable`; no finding claimed. |
| `provenance` | `no_credentials` | _none_ | — | The file was inspected; no C2PA manifest was attached. |
| `similarity` | `completed` | 1.0000 | — | A match indicates the same or near-identical media is present in another case in this instance, which is evidence of redistribution. It is not evidence of manipulation, and no match does not mean the media has not been shared elsewhere. |
| `risk_fusion` | `completed` | 0.6297 | — | Assessed HIGH impersonation risk (0.63 on a 0–1 scale) from 3 available forensic signal(s). DeepfakeBench Xception returned a manipulation signal of 0.42 for this media. No individual sampled frame crossed the suspicion threshold, so no specific time window is flagged. Best face similarity to Walkthrough Subject (demonstration) is 0.877, above the 0.60 same-person threshold, so the media does appear to depict the protected identity. This media also appears elsewhere in the local evidence index: 1 case(s) hold a byte-identical copy. The largest single contribution came from identity match (0.325 of the 0.63 total, at an effective weight of 0.38). 4 signal(s) were unavailable and excluded rather than assumed (voice match, audio/video consistency, content credentials (c2pa), audio editing indicators); they neither raised nor lowered this score. These are forensic indicators for investigator review, not proof of manipulation or of identity. |


The conclusions in the last column are each module's own words, read back from `GET /api/investigation/34`. Four modules returned no score at all — `not_applicable`, `unavailable` and `no_credentials` are reported as themselves rather than as a neutral 0.5, because a substituted number would move the fused risk score while looking like a measurement.

| Aggregate | Value |
|---|---|
| Overall risk score | `0.629713` |
| Risk level | `HIGH` |
| Frames extracted | `0` |


### What the analysis establishes

Again quoted from `GET /api/investigation/34/custody`, not paraphrased:

- **A probability of manipulation, not a verdict** — The manipulation model (DeepfakeBench Xception) returns a score for each sampled frame. The case score is a weighted fusion of only the signals that actually ran, and it is an investigative prioritisation aid.
- **Similarity to an enrolled reference, not identity** — Face comparison (FaceNet) and speaker comparison (ECAPA-TDNN) produce distances between embeddings. A high similarity means the media is consistent with the enrolled reference — it does not assert that the person is the same person.
- **Indicators measured over a sample** — Video is analysed on sampled frames rather than every frame, and audio on the extracted track. Findings describe what was examined, and the report states how much that was.
- **Results that are reproducible, and deliberately not preserved** — Analysis output is derived data: it can be discarded and recomputed from the preserved original at any time. Preserved evidence cannot be recomputed, which is why the two are stored separately and only one of them is hashed as a matter of record.


### What the analysis does not establish

- **Not who made the media, or with which tool** — No module attributes content to a creator, an account, a device or a generation tool. DeepTrace does not identify whoever produced a file.
- **Not intent, and not a criminal offence** — A score describes signal in a file. Whether an act was unlawful, and what was intended by it, is for an investigator and a court to determine.
- **Not a guarantee in either direction** — These models have measured error rates. A low score does not rule out manipulation, and a high score is not proof of it. Compression, re-uploading and screen recording all degrade the signal the models rely on.
- **Not authority over the preserved evidence** — Analysis never modifies a preserved file or its recorded digest. Re-running the pipeline can change the findings; it cannot change the evidence.


## Stage 5 — Comparing a circulating copy

_messaging-app style re-upload (1024 px long edge, JPEG q8), produced locally by ffmpeg_

| Field | Value |
|---|---|
| Locations on record | `2` |
| Copies actually retrieved and compared | `1` |


| Location / copy | Origin | Retrieval | Match type | Similarity | Label |
|---|---|---|---|---|---|
| `https://vis-www.cs.umass.edu/lfw/` | `public_url` | `rejected` | _not reported_ | — | — |
| `Copy recovered by the investigator` | `local_copy` | `fetched` | `near` | 1.0000 | High similarity |


A row with no match type is one DeepTrace could not retrieve. The reason is recorded rather than swallowed, and no similarity is invented for it:

- `https://vis-www.cs.umass.edu/lfw/` — Host could not be resolved (getaddrinfo failed).

### Why byte-identity is not enough, shown rather than asserted

The copy compared above is a genuine re-encode of the submitted file, produced by `ffmpeg` in this script — the same thing every platform does to media on upload. Its digest therefore differs, while the picture does not:

| Copy | SHA-256 |
|---|---|
| Submitted media | `325a8187df27cc01…879e9da6` |
| Re-encoded circulating copy | `59024b3464a0defd…75538005` |


Two different digests, one visual subject. This is precisely the case where hashing answers *nothing* and perceptual comparison answers the question, and it is why the two are reported separately throughout: the hash is an integrity control on what this system holds, not a way to recognise a re-shared file.

**Scope, quoted from the endpoint:** Only the URLs supplied here were retrieved. DeepTrace performs no internet-wide search and accesses no private or authenticated endpoint.

Absence of a match means only that nothing was found in what was checked.

## Stage 6 — The forensic report

| Field | Value |
|---|---|
| Generation | HTTP 200 |
| File | `data/walkthrough_case_34.pdf` |
| Size | `69741 bytes` |
| SHA-256 of the PDF, recomputed here | `4ebc6bd095f1c5ec…e259f7a9` |


The report is itself hashed, so a recipient can confirm the document they are reading is the document that was produced. It carries the case metadata, the custody chain, every module result including the unavailable ones, the hash-versus-inference boundary stated above, and the validation figures with their confidence intervals.

## What a reviewer should take from this

| Claim | Basis | Strength |
|---|---|---|
| These bytes are unaltered since receipt | SHA-256, recomputed independently above | **Arithmetic.** Verifiable by anyone, without trusting DeepTrace. |
| This report describes those bytes | Digest recorded in the report and in custody | **Arithmetic.** |
| The media shows signs consistent with manipulation | Module inference | **Evidence, with a measured error rate.** Not proof. |
| The face matches the enrolled person | Face embedding similarity at a measured threshold | **Evidence, with a measured false-match rate.** Not identification of a person. |
| A circulating copy is the same subject as the original | Perceptual comparison of a retrieved copy, hashes differing | **Evidence about reach.** Not an exhaustive search, and not byte-identity. |
| Someone committed an offence | — | **Not established.** Outside what this system can determine. |


---

Reproduce: start the backend, then `python scripts/walkthrough.py`. Open case #34 in the UI to see the same values in the interface. Validation figures live in `docs/VALIDATION.md` and are regenerated by `scripts/benchmark.py` and `scripts/robustness.py`.
