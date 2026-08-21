import os

from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from paths import PROJECT_ROOT

SQLALCHEMY_DATABASE_URL = f"sqlite:///{os.path.join(PROJECT_ROOT, 'deeptrace.db')}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate_sqlite():
    """Add columns introduced after the first local databases were created."""
    additions = {
        "identities": [
            ("consent_given", "BOOLEAN DEFAULT 0"),
            ("consent_text_version", "VARCHAR"),
            ("consent_at", "DATETIME"),
        ],
        "investigations": [
            ("source_urls", "TEXT"),
        ],
    }
    with engine.connect() as conn:
        for table, columns in additions.items():
            existing = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            if not existing:
                continue
            names = {row[1] for row in existing}
            for column_name, column_type in columns:
                if column_name not in names:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_type}"))
        conn.commit()
