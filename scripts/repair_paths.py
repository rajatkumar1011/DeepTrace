"""One-time repair for pre-1.0 relative evidence paths.

Before ``backend/paths.py`` existed, the backend wrote ``uploads/…`` and
``evidence/…`` as *relative* paths and resolved them against the current working
directory. Launching from ``backend/`` therefore created a second, parallel
``backend/uploads`` and ``backend/evidence`` tree, and the stored paths only
resolved when the process happened to start in the matching directory.

This script fixes the residue of that bug, without touching file contents:

  1. Relocates artifacts stranded under ``backend/`` into the canonical trees,
     never overwriting a file that already exists at the destination.
  2. Rewrites relative paths in the database to absolute paths.
  3. Re-hashes every relocated file and confirms it still matches the digest
     recorded in the database, so the move is provably content-preserving.

Idempotent: running it twice is a no-op. Run with ``--apply`` to make changes;
without it, the script only reports what it would do.
"""

import argparse
import os
import shutil
import sqlite3
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from paths import PROJECT_ROOT  # noqa: E402
from services.forensics import calculate_sha256  # noqa: E402

STRAY_ROOT = os.path.join(PROJECT_ROOT, "backend")
PATH_COLUMNS = (
    ("investigations", "file_path"),
    ("evidence", "file_path"),
    ("identities", "reference_image_path"),
    ("identities", "reference_audio_path"),
    ("trace_sources", "file_path"),
)


def locate(stored: str) -> tuple[str | None, str]:
    """Find the real file for a stored path and return (absolute_path, origin)."""
    normalised = stored.replace("\\", "/")
    canonical = os.path.abspath(os.path.join(PROJECT_ROOT, normalised))
    if os.path.isfile(canonical):
        return canonical, "canonical"
    stranded = os.path.abspath(os.path.join(STRAY_ROOT, normalised))
    if os.path.isfile(stranded):
        return stranded, "stranded"
    if os.path.isabs(stored) and os.path.isfile(stored):
        return os.path.abspath(stored), "absolute"
    return None, "missing"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Perform the repair. Without this flag the script only reports.")
    parser.add_argument("--db", default=os.path.join(PROJECT_ROOT, "deeptrace.db"))
    args = parser.parse_args()

    if not os.path.isfile(args.db):
        print(f"No database at {args.db}; nothing to repair.")
        return 0

    connection = sqlite3.connect(args.db)
    connection.row_factory = sqlite3.Row
    existing_tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }

    moved = relinked = already_ok = missing = hash_mismatch = 0

    for table, column in PATH_COLUMNS:
        if table not in existing_tables:
            continue
        has_hash = column == "file_path" and table in {"investigations", "evidence", "trace_sources"}
        select = f"SELECT id, {column} AS path" + (", sha256_hash" if has_hash else "") + \
                 f" FROM {table} WHERE {column} IS NOT NULL AND {column} != ''"
        for row in connection.execute(select).fetchall():
            stored = row["path"]
            found, origin = locate(stored)

            if origin == "missing":
                print(f"  MISSING  {table}#{row['id']}: {stored}")
                missing += 1
                continue

            target = os.path.abspath(os.path.join(PROJECT_ROOT, stored.replace("\\", "/")))

            if origin == "stranded":
                recorded = row["sha256_hash"] if has_hash else None
                if args.apply:
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    if os.path.exists(target):
                        print(f"  SKIP     {table}#{row['id']}: destination already exists")
                    else:
                        shutil.move(found, target)
                        print(f"  MOVED    {os.path.relpath(found, PROJECT_ROOT)} -> "
                              f"{os.path.relpath(target, PROJECT_ROOT)}")
                        moved += 1
                    if recorded:
                        if calculate_sha256(target) == recorded:
                            print(f"           hash verified after move")
                        else:
                            print(f"  WARNING  {table}#{row['id']} hash does NOT match after move")
                            hash_mismatch += 1
                else:
                    print(f"  WOULD MOVE {os.path.relpath(found, PROJECT_ROOT)} -> "
                          f"{os.path.relpath(target, PROJECT_ROOT)}")
                    moved += 1

            if os.path.isabs(stored) and origin != "stranded":
                already_ok += 1
                continue

            if args.apply:
                connection.execute(f"UPDATE {table} SET {column} = ? WHERE id = ?",
                                   (target, row["id"]))
            relinked += 1

    if args.apply:
        connection.commit()
    connection.close()

    print()
    print(f"{'Applied' if args.apply else 'Dry run'}: "
          f"{moved} file(s) relocated, {relinked} path(s) rewritten to absolute, "
          f"{already_ok} already absolute, {missing} missing, {hash_mismatch} hash mismatch(es).")
    if not args.apply:
        print("Re-run with --apply to perform the repair.")
    return 1 if hash_mismatch else 0


if __name__ == "__main__":
    raise SystemExit(main())
