from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services.crackmamba_detector import run_crackmamba_detection

router = APIRouter(prefix="/api/detection", tags=["detection"])


def _task_progress(task: models.InspectionTask, crack_count: int = 0) -> schemas.DetectionProgress:
    return schemas.DetectionProgress(
        task_id=task.id,
        status=task.status,
        progress_percent=int(task.progress_percent or 0),
        progress_message=task.progress_message or "",
        crack_count=crack_count,
        started_at=task.started_at,
        finished_at=task.finished_at,
    )


@router.post("/start/{task_id}", response_model=schemas.DetectionSummary)
def start_detection(
    task_id: int,
    payload: schemas.DetectionStartRequest | None = None,
    db: Session = Depends(get_db),
) -> schemas.DetectionSummary:
    task = db.get(models.InspectionTask, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    weight_name = payload.weight_name if payload else "crack9k"

    task.status = "detecting"
    task.started_at = datetime.utcnow()
    task.finished_at = None
    task.progress_percent = 3
    task.progress_message = "准备读取上传媒体"
    db.commit()

    try:
        task.progress_percent = 12
        task.progress_message = "抽取视频帧并匹配 SRT 元数据"
        db.commit()
        result = run_crackmamba_detection(db, task_id, weight_name=weight_name)
    except Exception as exc:
        db.rollback()
        failed_task = db.get(models.InspectionTask, task_id)
        if failed_task:
            failed_task.status = "failed"
            failed_task.progress_percent = 100
            failed_task.progress_message = "检测失败"
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"CrackMamba 检测失败: {exc}",
        ) from exc

    task = db.get(models.InspectionTask, task_id)
    if task:
        task.progress_percent = 100
        task.progress_message = task.progress_message or "检测完成"
        db.commit()
    return schemas.DetectionSummary(**result)


@router.get("/progress/{task_id}", response_model=schemas.DetectionProgress)
def get_detection_progress(task_id: int, db: Session = Depends(get_db)) -> schemas.DetectionProgress:
    task = db.get(models.InspectionTask, task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

    crack_count = (
        db.query(models.CrackRecord.id)
        .filter(models.CrackRecord.task_id == task_id)
        .count()
    )
    return _task_progress(task, crack_count=crack_count)
