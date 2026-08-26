"""Add self-declared case submitter identification storage.

Run from the backend directory with:

    python migrations/001_add_case_submitter.py

The migration is idempotent. It creates the new ``case_submitters`` table when
missing and adds ``investigations.submitter_id`` to an existing SQLite database.
It never deletes or rewrites existing investigations/evidence.
"""

from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, engine, migrate_sqlite  # noqa: E402
import models.schema  # noqa: F401,E402  Registers ORM tables with Base.


def main() -> None:
    Base.metadata.create_all(bind=engine)
    migrate_sqlite()
    print("DeepTrace migration complete: case_submitters + investigations.submitter_id are ready.")


if __name__ == "__main__":
    main()
