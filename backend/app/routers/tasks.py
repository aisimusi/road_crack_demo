from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app import models, schemas
from app.database import UPLOADS_DIR, get_db
from app.services.crackmamba_detector import delete_task_crack_data, uploaded_srt_paths
from app.services.geolocation import (
    PENDING_DISTRICT,
    PENDING_ROAD_NAME,
    apply_task_location_from_srt_paths,
    is_review_task_type,
    is_pending_location,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def get_or_create_road_segment(db: Session, road_name: str, district: str) -> models.RoadSegment:
    segment = (
        db.query(models.RoadSegment)
        .filter(models.RoadSegment.road_name == road_name, models.RoadSegment.district == district)
        .first()
    )
    if segment:
        return segment

    segment = models.RoadSegment(
        road_name=road_name,
        district=district,
        remark="由任务创建时自动补充",
    )
    db.add(segment)
    db.flush()
    return segment


def _resolve_media_path(media: models.MediaAsset) -> Path | None:
    if media.file_path:
        path = Path(media.file_path)
        if not path.is_absolute():
            path = UPLOADS_DIR.parent / media.file_path.lstrip("/")
        return path
    if media.file_uri.startswith("/uploads/"):
        return UPLOADS_DIR.parent / media.file_uri.lstrip("/")
    return None


def _delete_task_files(task: models.InspectionTask) -> None:
    for media in task.media_assets:
        file_path = _resolve_media_path(media)
        if file_path and file_path.exists() and file_path.is_file():
            file_path.unlink(missing_ok=True)

    work_dir = UPLOADS_DIR / "crackmamba" / f"task_{task.id:03d}"
    if work_dir.exists() and work_dir.is_dir():
        shutil.rmtree(work_dir)


@router.post("", response_model=schemas.InspectionTaskOut, status_code=status.HTTP_201_CREATED)
def create_task(payload: schemas.InspectionTaskCreate, db: Session = Depends(get_db)) -> models.InspectionTask:
    road_name = (payload.road_name or PENDING_ROAD_NAME).strip() or PENDING_ROAD_NAME
    district = (payload.district or PENDING_DISTRICT).strip() or PENDING_DISTRICT
    segment = None
    if not is_pending_location(road_name, district):
        segment = get_or_create_road_segment(db, road_name, district)
    task = models.InspectionTask(
        task_name=payload.task_name,
        road_name=road_name,
        district=district,
        operator_name=payload.operator_name,
        task_type=payload.task_type,
        road_match_status="pending" if is_review_task_type(payload.task_type) else "not_required",
        description=payload.description,
        scheduled_at=payload.scheduled_at,
        road_segment_id=segment.id if segment else None,
        progress_message="等待上传 SRT 匹配复检路段" if is_review_task_type(payload.task_type) else "等待上传 SRT 自动定位道路",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.get("", response_model=list[schemas.TaskListItem])
def list_tasks(db: Session = Depends(get_db)) -> list[schemas.TaskListItem]:
    rows = (
        db.query(
            models.InspectionTask,
            func.count(models.CrackRecord.id).label("crack_count"),
        )
        .outerjoin(models.CrackRecord, models.CrackRecord.task_id == models.InspectionTask.id)
        .group_by(models.InspectionTask.id)
        .order_by(models.InspectionTask.created_at.desc())
        .all()
    )

    results: list[schemas.TaskListItem] = []
    for task, crack_count in rows:
        results.append(
            schemas.TaskListItem(
                id=task.id,
                task_name=task.task_name,
                road_name=task.road_name,
                district=task.district,
                operator_name=task.operator_name,
                task_type=task.task_type,
                road_match_status=task.road_match_status,
                status=task.status,
                progress_percent=task.progress_percent,
                progress_message=task.progress_message,
                description=task.description,
                scheduled_at=task.scheduled_at,
                started_at=task.started_at,
                finished_at=task.finished_at,
                road_segment_id=task.road_segment_id,
                created_at=task.created_at,
                updated_at=task.updated_at,
                crack_count=int(crack_count or 0),
            )
        )
    return results


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, db: Session = Depends(get_db)) -> Response:
    task = (
        db.query(models.InspectionTask)
        .options(
            joinedload(models.InspectionTask.media_assets),
        )
        .filter(models.InspectionTask.id == task_id)
        .first()
    )
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

    _delete_task_files(task)
    delete_task_crack_data(db, task.id)
    db.delete(task)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{task_id}", response_model=schemas.TaskDetail)
def get_task(task_id: int, db: Session = Depends(get_db)) -> models.InspectionTask:
    task = (
        db.query(models.InspectionTask)
        .options(
            joinedload(models.InspectionTask.road_segment),
            joinedload(models.InspectionTask.media_assets),
            joinedload(models.InspectionTask.frames),
            joinedload(models.InspectionTask.crack_records),
        )
        .filter(models.InspectionTask.id == task_id)
        .first()
    )
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return task


@router.post("/{task_id}/relocate", response_model=schemas.InspectionTaskOut)
def relocate_task(task_id: int, db: Session = Depends(get_db)) -> models.InspectionTask:
    task = (
        db.query(models.InspectionTask)
        .options(joinedload(models.InspectionTask.media_assets))
        .filter(models.InspectionTask.id == task_id)
        .first()
    )
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

    srt_paths = uploaded_srt_paths(task.media_assets)
    if not srt_paths:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前任务还没有上传 SRT 文件")

    location = apply_task_location_from_srt_paths(db, task, srt_paths)
    db.query(models.CrackRecord).filter(models.CrackRecord.task_id == task.id).update(
        {
            models.CrackRecord.road_segment_id: task.road_segment_id,
            models.CrackRecord.road_name: location.road_name,
            models.CrackRecord.district: location.district,
        },
        synchronize_session=False,
    )
    db.query(models.InspectionFrame).filter(models.InspectionFrame.task_id == task.id).update(
        {
            models.InspectionFrame.road_segment_id: task.road_segment_id,
            models.InspectionFrame.road_name: location.road_name,
            models.InspectionFrame.district: location.district,
        },
        synchronize_session=False,
    )
    if task.status != "detecting":
        if is_review_task_type(task.task_type) and task.road_match_status == "matched_existing":
            task.progress_message = "复检路段已通过 SRT 经纬度匹配到系统已有路段"
        elif is_review_task_type(task.task_type):
            task.progress_message = "复检任务未匹配到系统已有路段，仅保存检测结果"
        elif location.source == "coordinates":
            task.progress_message = "已根据 SRT 重新定位到坐标范围，等待地图服务返回道路名"
        else:
            task.progress_message = "已根据 SRT 重新定位道路"
    db.commit()
    db.refresh(task)
    return task
