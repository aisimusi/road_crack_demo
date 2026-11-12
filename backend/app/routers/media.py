from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import MEDIA_UPLOAD_DIR, get_db
from app.services.geolocation import apply_task_location_from_srt

router = APIRouter(prefix="/api/media", tags=["media"])

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}
SRT_EXTENSIONS = {".srt"}
ALLOWED_ASSET_TYPES = {"video", "srt"}


@router.post("/upload", response_model=schemas.MediaAssetOut, status_code=status.HTTP_201_CREATED)
async def upload_media(
    file: UploadFile = File(...),
    task_id: int | None = Form(default=None),
    asset_type: str = Form(default="image"),
    category: str = Form(default="uploaded"),
    db: Session = Depends(get_db),
) -> models.MediaAsset:
    task = db.get(models.InspectionTask, task_id) if task_id is not None else None
    if task_id is not None and not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

    original_name = Path(file.filename or "upload.dat")
    suffix = original_name.suffix.lower() or ".dat"
    if asset_type not in ALLOWED_ASSET_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="仅支持上传视频和 SRT 文件")
    if asset_type == "video" and suffix not in VIDEO_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="视频文件仅支持 mp4/mov/avi/mkv/m4v")
    if asset_type == "srt" and suffix not in SRT_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SRT 元数据文件必须为 .srt")

    target_name = f"{uuid4().hex}{suffix}"
    target_path = MEDIA_UPLOAD_DIR / target_name

    with target_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    media = models.MediaAsset(
        task_id=task_id,
        asset_type=asset_type,
        category=category,
        file_name=original_name.name,
        file_path=str(target_path),
        file_uri=f"/uploads/media/{target_name}",
        mime_type=file.content_type or "application/octet-stream",
    )
    db.add(media)
    if asset_type == "srt" and task:
        try:
            apply_task_location_from_srt(db, task, target_path)
        except ValueError as exc:
            db.rollback()
            target_path.unlink(missing_ok=True)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    db.refresh(media)
    return media


@router.get("/task/{task_id}", response_model=list[schemas.MediaAssetOut])
def get_task_media(task_id: int, db: Session = Depends(get_db)) -> list[models.MediaAsset]:
    if not db.get(models.InspectionTask, task_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

    return (
        db.query(models.MediaAsset)
        .filter(models.MediaAsset.task_id == task_id)
        .order_by(models.MediaAsset.created_at.desc())
        .all()
    )
