import os

from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from paths import PROJECT_ROOT

# DEEPTRACE_DB_PATH lets the test suite point at a throwaway database without
# touching the developer's working evidence store.
DB_PATH = os.environ.get("DEEPTRACE_DB_PATH") or os.path.join(PROJECT_ROOT, "deeptrace.db")
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Columns added after the first local databases were created. SQLite cannot add
# them via create_all(), so they are applied additively at startup. Only ADD
# COLUMN is used — no destructive migration ever runs against evidence data.
_COLUMN_ADDITIONS = {
    "identities": [
        ("consent_given", "BOOLEAN DEFAULT 0"),
        ("consent_text_version", "VARCHAR"),
        ("consent_at", "DATETIME"),
        ("face_model", "VARCHAR"),
        ("voice_model", "VARCHAR"),
    ],
    "investigations": [
        ("source_urls", "TEXT"),
        ("perceptual_hash", "VARCHAR"),
        ("progress_stage", "VARCHAR"),
        ("progress_percent", "INTEGER DEFAULT 0"),
        ("error_message", "VARCHAR"),
        ("has_audio_stream", "BOOLEAN"),
        ("media_metadata", "TEXT"),
        ("analysis_started_at", "DATETIME"),
        ("analysis_completed_at", "DATETIME"),
    ],
    "analysis_results": [
        ("status", "VARCHAR"),
    ],
}


def migrate_sqlite() -> None:
    with engine.connect() as conn:
        for table, columns in _COLUMN_ADDITIONS.items():
            existing = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            if not existing:
                continue
            names = {row[1] for row in existing}
            for column_name, column_type in columns:
                if column_name not in names:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_type}"))
        conn.commit()
