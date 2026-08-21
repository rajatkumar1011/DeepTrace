import requests
import json
import hashlib
import os

base = "http://127.0.0.1:8000"

# ── 1. SHA-256 integrity verification ─────────────────────────
print("=" * 60)
print("TEST 1: SHA-256 INTEGRITY VERIFICATION")
print("=" * 60)

# Get investigation and verify the hash matches actual file
r = requests.get(f"{base}/api/investigation/10", timeout=10)
d = r.json()
stored_hash = d["sha256_hash"]
print(f"  INV#10 stored SHA-256: {stored_hash}")

# Find the uploaded file path
orig_evidence = [e for e in d["evidence"] if e["type"] == "original"]
if orig_evidence:
    fpath = orig_evidence[0]["file_path"]
    ev_sha = orig_evidence[0]["sha256"]
    print(f"  Evidence stored SHA: {ev_sha}")
    print(f"  Investigation SHA == Evidence SHA: {stored_hash == ev_sha}")

    # Recalculate the hash from the actual file
    if os.path.exists(fpath):
        sha = hashlib.sha256()
        with open(fpath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha.update(chunk)
        recalc = sha.hexdigest()
        print(f"  Recalculated SHA-256: {recalc}")
        print(f"  Hash integrity match: {recalc == stored_hash}")
    else:
        print(f"  File path not accessible directly: {fpath}")

# ── 2. Frame evidence inspection ───────────────────────────────
print()
print("=" * 60)
print("TEST 2: FRAME EVIDENCE ARTIFACTS")
print("=" * 60)

r2 = requests.get(f"{base}/api/investigation/10", timeout=10)
d2 = r2.json()
all_evidence = d2["evidence"]
frames = [e for e in all_evidence if e["type"] == "frame"]
print(f"  Total evidence items: {len(all_evidence)}")
print(f"  Frame artifacts: {len(frames)}")
print(f"  frames_extracted field: {d2['frames_extracted']}")
print()
for ev in frames[:5]:
    print(f"  frame | ts={str(ev.get('timestamp_offset', 'N/A')):6}s | "
          f"sha256={str(ev.get('sha256',''))[:20]}... | "
          f"phash={ev.get('perceptual_hash', 'N/A')}")
    # Verify frame file is actually accessible via static serving
    rel_path = ev["file_path"].replace("\\", "/")
    frame_url = f"{base}/evidence/{rel_path.split('evidence/')[-1]}"
    try:
        fr = requests.get(frame_url, timeout=5)
        print(f"         HTTP GET frame → {fr.status_code} ({fr.headers.get('Content-Type','?')})")
    except Exception as e:
        print(f"         HTTP GET frame → ERROR: {e}")

# ── 3. Evidence endpoint ───────────────────────────────────────
print()
print("=" * 60)
print("TEST 3: /api/investigation/{id}/evidence ENDPOINT")
print("=" * 60)
r3 = requests.get(f"{base}/api/investigation/10/evidence", timeout=10)
print(f"  Status: {r3.status_code}")
evlist = r3.json()
print(f"  Total evidence items returned: {len(evlist)}")
types = {}
for ev in evlist:
    t = ev["type"]
    types[t] = types.get(t, 0) + 1
print(f"  By type: {types}")

# Verify pHash is stored for frame items
phash_count = sum(1 for e in evlist if e.get("perceptual_hash"))
sha_count = sum(1 for e in evlist if e.get("sha256"))
print(f"  Items with perceptual_hash: {phash_count}")
print(f"  Items with sha256: {sha_count}")

# ── 4. Timeline endpoint ───────────────────────────────────────
print()
print("=" * 60)
print("TEST 4: INVESTIGATION TIMELINE (AUDIT TRAIL)")
print("=" * 60)
r4 = requests.get(f"{base}/api/investigation/10/timeline", timeout=10)
print(f"  Status: {r4.status_code}")
events = r4.json()
print(f"  Total timeline events: {len(events)}")
print()
for ev in events:
    ts = str(ev.get("created_at", ""))[:19]
    etype = ev.get("event_type", "")
    desc = ev.get("description", "")
    print(f"  [{ts}] {etype:25} | {desc[:60]}")

# ── 5. Cross-check: same SHA-256 for same file ─────────────────
print()
print("=" * 60)
print("TEST 5: DETERMINISTIC SHA-256 (same file = same hash)")
print("=" * 60)
r5a = requests.get(f"{base}/api/investigation/8", timeout=10)
r5b = requests.get(f"{base}/api/investigation/7", timeout=10)
da = r5a.json()
db_ = r5b.json()
print(f"  INV#8 (lena_with_id.jpg): {da['sha256_hash']}")
print(f"  INV#7 (lena.jpg)        : {db_['sha256_hash']}")
print(f"  Hashes match (same image): {da['sha256_hash'] == db_['sha256_hash']}")
