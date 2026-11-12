from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
UPLOADS_DIR = BACKEND_DIR / "uploads"
IMAGES_UPLOAD_DIR = UPLOADS_DIR / "images"
RESULTS_UPLOAD_DIR = UPLOADS_DIR / "results"
MASKS_UPLOAD_DIR = UPLOADS_DIR / "masks"
MEDIA_UPLOAD_DIR = UPLOADS_DIR / "media"
DATABASE_PATH = BACKEND_DIR / "road_crack_demo.db"

for directory in (UPLOADS_DIR, IMAGES_UPLOAD_DIR, RESULTS_UPLOAD_DIR, MASKS_UPLOAD_DIR, MEDIA_UPLOAD_DIR):
    directory.mkdir(parents=True, exist_ok=True)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
