from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from PIL import Image, UnidentifiedImageError
from sqlalchemy import case, desc, func
from sqlalchemy.orm import Session, joinedload

from app import models, schemas
from app.database import UPLOADS_DIR, get_db
from app.services.crackmamba_detector import resolve_file_uri_to_path

router = APIRouter(prefix="/api/cracks", tags=["cracks"])
CROPS_UPLOAD_DIR = UPLOADS_DIR / "crops"
CROPS_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAP_TASK_SEVERITY_DISPLAY_LIMITS = {
    3: 19,  # 严格按“严重 < 20 个”控制
    2: 14,  # 严格按“中等 < 15 个”控制
    1: 9,   # 严格按“轻微 < 10 个”控制
}
CRACK_TYPE_LABELS = {
    "alligator_crack": "网裂",
    "longitudinal_crack": "纵向裂缝",
    "oblique_crack": "斜向裂缝",
    "repair_or_pothole": "修补/坑洞",
    "transverse_crack": "横向裂缝",
    "unknown": "未分类",
    "none": "未检测到",
}


def _display_crack_type(value: str | None) -> str:
    normalized = (value or "").strip()
    return CRACK_TYPE_LABELS.get(normalized, normalized or "未分类")


def _crop_bounds(record: models.CrackRecord, image_width: int, image_height: int) -> tuple[int, int, int, int]:
    bbox_x = max(0, int(record.bbox_x or 0))
    bbox_y = max(0, int(record.bbox_y or 0))
    bbox_width = max(1, int(record.bbox_width or 1))
    bbox_height = max(1, int(record.bbox_height or 1))
    padding_x = max(24, int(bbox_width * 0.3))
    padding_y = max(24, int(bbox_height * 0.3))

    left = max(0, bbox_x - padding_x)
    top = max(0, bbox_y - padding_y)
    right = min(image_width, bbox_x + bbox_width + padding_x)
    bottom = min(image_height, bbox_y + bbox_height + padding_y)

    if right <= left:
        right = min(image_width, left + max(1, bbox_width))
    if bottom <= top:
        bottom = min(image_height, top + max(1, bbox_height))
    return left, top, right, bottom


def _build_crop_uri(record: models.CrackRecord, variant: str) -> str | None:
    source_uri = record.result_image_uri if variant == "result" else record.original_image_uri
    if not source_uri:
        return None

    try:
        source_path = resolve_file_uri_to_path(source_uri)
    except OSError:
        return None
    if not source_path.exists() or not source_path.is_file():
        return None

    target_path = CROPS_UPLOAD_DIR / f"crack_{record.id}_{variant}_crop.png"
    if target_path.exists() and target_path.stat().st_mtime >= source_path.stat().st_mtime:
        return f"/uploads/crops/{target_path.name}"

    try:
        with Image.open(source_path) as image:
            left, top, right, bottom = _crop_bounds(record, image.width, image.height)
            cropped = image.crop((left, top, right, bottom))
            cropped.save(target_path, format="PNG")
    except (FileNotFoundError, OSError, UnidentifiedImageError):
        return source_uri
    return f"/uploads/crops/{target_path.name}"


def _serialize_observation_image(record: models.CrackRecord) -> schemas.CrackObservationImage:
    return schemas.CrackObservationImage(
        crack_id=record.id,
        crack_code=record.crack_code,
        task_id=record.task_id,
        severity_level=record.severity_level,
        severity_label=record.severity_label,
        detected_at=record.detected_at,
        original_image_uri=record.original_image_uri,
        result_image_uri=record.result_image_uri,
        crop_original_image_uri=_build_crop_uri(record, "original"),
        crop_result_image_uri=_build_crop_uri(record, "result"),
        bbox_x=record.bbox_x,
        bbox_y=record.bbox_y,
        bbox_width=record.bbox_width,
        bbox_height=record.bbox_height,
    )


def _serialize_crack_record(record: models.CrackRecord) -> schemas.CrackRecordOut:
    payload = schemas.CrackRecordOut.model_validate(record)
    payload.crack_type = _display_crack_type(payload.crack_type)
    return payload


def _serialize_crack_identity(identity: models.CrackIdentity) -> schemas.CrackIdentityOut:
    payload = schemas.CrackIdentityOut.model_validate(identity)
    payload.crack_type = _display_crack_type(payload.crack_type)
    return payload


def _serialize_frame_crack(record: models.CrackRecord) -> schemas.FrameCrackOut:
    return schemas.FrameCrackOut(
        id=record.id,
        identity_id=record.identity_id,
        identity_code=record.identity.identity_code if record.identity else None,
        crack_code=record.crack_code,
        crack_type=_display_crack_type(record.crack_type),
        severity_level=record.severity_level,
        severity_label=record.severity_label,
        length_m=record.length_m,
        avg_width_cm=record.avg_width_cm,
        max_width_cm=record.max_width_cm,
        area_m2=record.area_m2,
        longitude=record.longitude,
        latitude=record.latitude,
        original_image_uri=record.original_image_uri,
        result_image_uri=record.result_image_uri,
        crop_original_image_uri=_build_crop_uri(record, "original"),
        crop_result_image_uri=_build_crop_uri(record, "result"),
        bbox_x=record.bbox_x,
        bbox_y=record.bbox_y,
        bbox_width=record.bbox_width,
        bbox_height=record.bbox_height,
    )


def _limit_map_points_per_task(
    point_rows: list[tuple[int | None, schemas.CrackMapPoint]],
) -> list[schemas.CrackMapPoint]:
    counters: dict[tuple[int, int], int] = {}
    limited_points: list[schemas.CrackMapPoint] = []

    for task_id, point in point_rows:
        severity_level = int(point.severity_level or 0)
        limit = MAP_TASK_SEVERITY_DISPLAY_LIMITS.get(severity_level)
        if limit is None:
            limited_points.append(point)
            continue

        bucket = (int(task_id or 0), severity_level)
        current_count = counters.get(bucket, 0)
        if current_count >= limit:
            continue

        counters[bucket] = current_count + 1
        limited_points.append(point)

    return limited_points


def _serialize_inspection_frame(db: Session, frame: models.InspectionFrame) -> schemas.InspectionFrameOut:
    records = (
        db.query(models.CrackRecord)
        .filter(models.CrackRecord.frame_id == frame.id)
        .order_by(models.CrackRecord.severity_level.desc(), models.CrackRecord.area_m2.desc(), models.CrackRecord.id.asc())
        .all()
    )
    return schemas.InspectionFrameOut(
        id=frame.id,
        task_id=frame.task_id,
        road_segment_id=frame.road_segment_id,
        frame_code=frame.frame_code,
        road_name=frame.road_name,
        district=frame.district,
        task_name=frame.task.task_name if frame.task else None,
        task_type=frame.task.task_type if frame.task else None,
        captured_at=frame.captured_at,
        elapsed_seconds=frame.elapsed_seconds,
        longitude=frame.longitude,
        latitude=frame.latitude,
        original_image_uri=frame.original_image_uri,
        result_image_uri=frame.result_image_uri,
        mask_image_uri=frame.mask_image_uri,
        crack_count=frame.crack_count,
        max_severity_level=frame.max_severity_level,
        max_severity_label=frame.max_severity_label,
        total_area_m2=frame.total_area_m2,
        remark=frame.remark,
        created_at=frame.created_at,
        cracks=[_serialize_frame_crack(record) for record in records],
    )


@router.get("", response_model=list[schemas.CrackRecordOut])
def list_cracks(
    road_name: str | None = Query(default=None),
    severity_level: int | None = Query(default=None, ge=1, le=3),
    db: Session = Depends(get_db),
) -> list[schemas.CrackRecordOut]:
    query = db.query(models.CrackRecord)
    if road_name:
        query = query.filter(models.CrackRecord.road_name == road_name)
    if severity_level:
        query = query.filter(models.CrackRecord.severity_level == severity_level)
    records = query.order_by(models.CrackRecord.detected_at.desc(), models.CrackRecord.id.desc()).all()
    return [_serialize_crack_record(item) for item in records]


@router.get("/map", response_model=list[schemas.CrackMapPoint])
def get_crack_map_points(
    road_name: str | None = Query(default=None),
    severity_level: int | None = Query(default=None, ge=1, le=3),
    db: Session = Depends(get_db),
) -> list[schemas.CrackMapPoint]:
    identity_query = db.query(models.CrackIdentity)
    if road_name:
        identity_query = identity_query.filter(models.CrackIdentity.road_name == road_name)
    if severity_level:
        identity_query = identity_query.filter(models.CrackIdentity.current_severity_level == severity_level)

    identities = identity_query.order_by(models.CrackIdentity.last_seen_at.desc()).all()
    if identities:
        point_rows: list[tuple[int | None, schemas.CrackMapPoint]] = []
        for identity in identities:
            latest_record = (
                db.query(models.CrackRecord)
                .filter(models.CrackRecord.identity_id == identity.id)
                .options(joinedload(models.CrackRecord.frame))
                .order_by(models.CrackRecord.detected_at.desc())
                .first()
            )
            frame = latest_record.frame if latest_record else None
            point_rows.append(
                (
                    latest_record.task_id if latest_record else identity.last_task_id,
                    schemas.CrackMapPoint(
                        crack_id=latest_record.id if latest_record else identity.id,
                        identity_id=identity.id,
                        frame_id=latest_record.frame_id if latest_record else None,
                        identity_code=identity.identity_code,
                        crack_code=latest_record.crack_code if latest_record else identity.identity_code,
                        road_name=identity.road_name,
                        district=identity.district,
                        severity_level=identity.current_severity_level,
                        severity_label=identity.current_severity_label,
                        crack_type=_display_crack_type(identity.crack_type),
                        length_m=identity.current_length_m,
                        avg_width_cm=identity.current_avg_width_cm,
                        area_m2=identity.current_area_m2,
                        longitude=identity.latest_longitude,
                        latitude=identity.latest_latitude,
                        result_image_uri=identity.latest_result_image_uri or "",
                        original_image_uri=(
                            frame.original_image_uri if frame and frame.original_image_uri else identity.latest_original_image_uri
                        ),
                        mask_image_uri=frame.mask_image_uri if frame else None,
                        detected_at=latest_record.detected_at if latest_record else identity.last_seen_at,
                        lifecycle_status=identity.lifecycle_status,
                        maintenance_status=identity.maintenance_status,
                        priority_level=identity.priority_level,
                    ),
                )
            )
        return _limit_map_points_per_task(point_rows)

    query = db.query(models.CrackRecord).options(joinedload(models.CrackRecord.identity), joinedload(models.CrackRecord.frame))
    if road_name:
        query = query.filter(models.CrackRecord.road_name == road_name)
    if severity_level:
        query = query.filter(models.CrackRecord.severity_level == severity_level)

    records = query.order_by(models.CrackRecord.detected_at.desc()).all()
    point_rows = [
        (
            item.task_id,
            schemas.CrackMapPoint(
                crack_id=item.id,
                identity_id=item.identity_id,
                frame_id=item.frame_id,
                identity_code=item.identity.identity_code if item.identity else None,
                crack_code=item.crack_code,
                road_name=item.road_name,
                district=item.district,
                severity_level=item.severity_level,
                severity_label=item.severity_label,
                crack_type=_display_crack_type(item.crack_type),
                length_m=item.length_m,
                avg_width_cm=item.avg_width_cm,
                area_m2=item.area_m2,
                longitude=item.longitude,
                latitude=item.latitude,
                result_image_uri=item.result_image_uri,
                original_image_uri=item.frame.original_image_uri if item.frame else item.original_image_uri,
                mask_image_uri=item.frame.mask_image_uri if item.frame else None,
                detected_at=item.detected_at,
                lifecycle_status=item.identity.lifecycle_status if item.identity else None,
                maintenance_status=item.identity.maintenance_status if item.identity else None,
                priority_level=item.identity.priority_level if item.identity else None,
            ),
        )
        for item in records
    ]
    return _limit_map_points_per_task(point_rows)


@router.get("/statistics", response_model=schemas.CrackStatistics)
def get_crack_statistics(db: Session = Depends(get_db)) -> schemas.CrackStatistics:
    total_observations = db.query(func.count(models.CrackRecord.id)).scalar() or 0
    total_identities = db.query(func.count(models.CrackIdentity.id)).scalar() or 0
    total_frames = db.query(func.count(models.InspectionFrame.id)).scalar() or 0
    active_identity_count = (
        db.query(func.count(models.CrackIdentity.id))
        .filter(models.CrackIdentity.lifecycle_status == "active")
        .scalar()
        or 0
    )
    repaired_identity_count = (
        db.query(func.count(models.CrackIdentity.id))
        .filter(models.CrackIdentity.lifecycle_status == "repaired")
        .scalar()
        or 0
    )
    recurred_identity_count = (
        db.query(func.count(models.CrackIdentity.id))
        .filter(models.CrackIdentity.lifecycle_status == "recurred")
        .scalar()
        or 0
    )
    total_cracks = total_identities or total_observations
    severe_count = (
        db.query(func.count(models.CrackIdentity.id))
        .filter(models.CrackIdentity.current_severity_level == 3)
        .scalar()
        or 0
    )
    medium_count = (
        db.query(func.count(models.CrackIdentity.id))
        .filter(models.CrackIdentity.current_severity_level == 2)
        .scalar()
        or 0
    )
    minor_count = (
        db.query(func.count(models.CrackIdentity.id))
        .filter(models.CrackIdentity.current_severity_level == 1)
        .scalar()
        or 0
    )
    if not total_identities:
        severe_count = (
            db.query(func.count(models.CrackRecord.id))
            .filter(models.CrackRecord.severity_level == 3)
            .scalar()
            or 0
        )
        medium_count = (
            db.query(func.count(models.CrackRecord.id))
            .filter(models.CrackRecord.severity_level == 2)
            .scalar()
            or 0
        )
        minor_count = (
            db.query(func.count(models.CrackRecord.id))
            .filter(models.CrackRecord.severity_level == 1)
            .scalar()
            or 0
        )
    road_count = db.query(func.count(func.distinct(models.CrackIdentity.road_name))).scalar() or 0
    if not road_count:
        road_count = db.query(func.count(func.distinct(models.CrackRecord.road_name))).scalar() or 0
    task_count = db.query(func.count(models.InspectionTask.id)).scalar() or 0
    finished_task_count = (
        db.query(func.count(models.InspectionTask.id))
        .filter(models.InspectionTask.status == "finished")
        .scalar()
        or 0
    )

    recent_cracks = (
        db.query(models.CrackRecord)
        .order_by(models.CrackRecord.detected_at.desc())
        .limit(6)
        .all()
    )
    road_rows = (
        db.query(
            models.CrackIdentity.road_name,
            func.count(models.CrackIdentity.id).label("crack_count"),
        )
        .group_by(models.CrackIdentity.road_name)
        .order_by(desc("crack_count"), models.CrackIdentity.road_name.asc())
        .limit(8)
        .all()
    )
    if not road_rows:
        road_rows = (
            db.query(
                models.CrackRecord.road_name,
                func.count(models.CrackRecord.id).label("crack_count"),
            )
            .group_by(models.CrackRecord.road_name)
            .order_by(desc("crack_count"), models.CrackRecord.road_name.asc())
            .limit(8)
            .all()
        )

    return schemas.CrackStatistics(
        total_cracks=int(total_cracks),
        total_observations=int(total_observations),
        total_identities=int(total_identities),
        total_frames=int(total_frames),
        active_identity_count=int(active_identity_count),
        repaired_identity_count=int(repaired_identity_count),
        recurred_identity_count=int(recurred_identity_count),
        severe_count=int(severe_count),
        medium_count=int(medium_count),
        minor_count=int(minor_count),
        road_count=int(road_count),
        task_count=int(task_count),
        finished_task_count=int(finished_task_count),
        recent_cracks=[_serialize_crack_record(item) for item in recent_cracks],
        road_breakdown=[
            schemas.RoadCrackCount(road_name=row.road_name, crack_count=int(row.crack_count))
            for row in road_rows
        ],
    )


@router.get("/frame-roads", response_model=list[schemas.RoadInspectionSummary])
def list_frame_roads(db: Session = Depends(get_db)) -> list[schemas.RoadInspectionSummary]:
    rows = (
        db.query(
            models.InspectionFrame.road_segment_id,
            models.InspectionFrame.road_name,
            models.InspectionFrame.district,
            func.count(func.distinct(models.InspectionFrame.task_id)).label("task_count"),
            func.count(models.InspectionFrame.id).label("frame_count"),
            func.sum(models.InspectionFrame.crack_count).label("crack_count"),
            func.max(models.InspectionFrame.captured_at).label("last_detected_at"),
        )
        .group_by(models.InspectionFrame.road_segment_id, models.InspectionFrame.road_name, models.InspectionFrame.district)
        .order_by(desc("last_detected_at"))
        .all()
    )
    return [
        schemas.RoadInspectionSummary(
            road_segment_id=row.road_segment_id,
            road_name=row.road_name,
            district=row.district,
            task_count=int(row.task_count or 0),
            frame_count=int(row.frame_count or 0),
            crack_count=int(row.crack_count or 0),
            last_detected_at=row.last_detected_at,
        )
        for row in rows
    ]


@router.get("/frame-dates", response_model=list[schemas.TaskInspectionDate])
def list_frame_dates(
    road_segment_id: int | None = Query(default=None),
    road_name: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[schemas.TaskInspectionDate]:
    query = (
        db.query(
            models.InspectionTask.id.label("task_id"),
            models.InspectionTask.task_name,
            models.InspectionTask.task_type,
            models.InspectionTask.started_at,
            models.InspectionTask.finished_at,
            func.max(models.InspectionFrame.captured_at).label("latest_frame_at"),
            func.count(models.InspectionFrame.id).label("frame_count"),
            func.sum(models.InspectionFrame.crack_count).label("crack_count"),
            func.sum(case((models.InspectionFrame.max_severity_level == 3, models.InspectionFrame.crack_count), else_=0)).label("severe_count"),
        )
        .join(models.InspectionFrame, models.InspectionFrame.task_id == models.InspectionTask.id)
    )
    if road_segment_id is not None:
        query = query.filter(models.InspectionFrame.road_segment_id == road_segment_id)
    elif road_name:
        query = query.filter(models.InspectionFrame.road_name == road_name)

    rows = (
        query.group_by(models.InspectionTask.id)
        .order_by(desc("latest_frame_at"), models.InspectionTask.id.desc())
        .all()
    )
    results: list[schemas.TaskInspectionDate] = []
    for row in rows:
        date_source = row.latest_frame_at or row.finished_at or row.started_at
        detected_date = date_source.date().isoformat() if date_source else "-"
        results.append(
            schemas.TaskInspectionDate(
                task_id=row.task_id,
                task_name=row.task_name,
                task_type=row.task_type,
                detected_date=detected_date,
                started_at=row.started_at,
                finished_at=row.finished_at,
                frame_count=int(row.frame_count or 0),
                crack_count=int(row.crack_count or 0),
                severe_count=int(row.severe_count or 0),
            )
        )
    return results


@router.get("/frames", response_model=schemas.InspectionFramePage)
def list_inspection_frames(
    road_segment_id: int | None = Query(default=None),
    road_name: str | None = Query(default=None),
    task_id: int | None = Query(default=None),
    detected_date: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
) -> schemas.InspectionFramePage:
    query = db.query(models.InspectionFrame)
    if road_segment_id is not None:
        query = query.filter(models.InspectionFrame.road_segment_id == road_segment_id)
    elif road_name:
        query = query.filter(models.InspectionFrame.road_name == road_name)
    if task_id is not None:
        query = query.filter(models.InspectionFrame.task_id == task_id)
    if detected_date:
        query = query.filter(func.date(models.InspectionFrame.captured_at) == detected_date)

    total = query.count()
    total_pages = max((total + page_size - 1) // page_size, 1)
    frames = (
        query.order_by(models.InspectionFrame.captured_at.desc(), models.InspectionFrame.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return schemas.InspectionFramePage(
        items=[_serialize_inspection_frame(db, frame) for frame in frames],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/frames/{frame_id}", response_model=schemas.InspectionFrameOut)
def get_inspection_frame(frame_id: int, db: Session = Depends(get_db)) -> schemas.InspectionFrameOut:
    frame = db.get(models.InspectionFrame, frame_id)
    if not frame:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="帧检测记录不存在")
    return _serialize_inspection_frame(db, frame)


@router.get("/identities", response_model=list[schemas.CrackIdentityOut])
def list_crack_identities(
    task_id: int | None = Query(default=None),
    road_segment_id: int | None = Query(default=None),
    road_name: str | None = Query(default=None),
    severity_level: int | None = Query(default=None, ge=1, le=3),
    lifecycle_status: str | None = Query(default=None),
    maintenance_status: str | None = Query(default=None),
    priority_level: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[schemas.CrackIdentityOut]:
    query = db.query(models.CrackIdentity)
    if task_id is not None:
        query = query.join(models.CrackRecord, models.CrackRecord.identity_id == models.CrackIdentity.id).filter(
            models.CrackRecord.task_id == task_id,
        )
    if road_segment_id is not None:
        query = query.filter(models.CrackIdentity.road_segment_id == road_segment_id)
    if road_name:
        query = query.filter(models.CrackIdentity.road_name == road_name)
    if severity_level:
        query = query.filter(models.CrackIdentity.current_severity_level == severity_level)
    if lifecycle_status:
        query = query.filter(models.CrackIdentity.lifecycle_status == lifecycle_status)
    if maintenance_status:
        query = query.filter(models.CrackIdentity.maintenance_status == maintenance_status)
    if priority_level:
        query = query.filter(models.CrackIdentity.priority_level == priority_level)
    identities = query.order_by(
        models.CrackIdentity.priority_level.desc(),
        models.CrackIdentity.current_severity_level.desc(),
        models.CrackIdentity.last_seen_at.desc(),
    ).distinct().all()
    return [_serialize_crack_identity(item) for item in identities]


@router.get("/identities/{identity_id}", response_model=schemas.CrackIdentityDetailWithImages)
def get_crack_identity_detail(identity_id: int, db: Session = Depends(get_db)) -> schemas.CrackIdentityDetailWithImages:
    identity = db.get(models.CrackIdentity, identity_id)
    if not identity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="裂缝身份档案不存在")
    records = (
        db.query(models.CrackRecord)
        .filter(models.CrackRecord.identity_id == identity_id)
        .order_by(models.CrackRecord.detected_at.desc())
        .all()
    )
    maintenance_records = (
        db.query(models.MaintenanceRecord)
        .filter(models.MaintenanceRecord.identity_id == identity_id)
        .order_by(models.MaintenanceRecord.created_at.desc())
        .all()
    )
    payload = schemas.CrackIdentityDetailWithImages.model_validate(identity)
    payload.crack_type = _display_crack_type(payload.crack_type)
    payload.records = [_serialize_crack_record(item) for item in records]
    payload.maintenance_records = [schemas.MaintenanceRecordOut.model_validate(item) for item in maintenance_records]
    payload.observation_images = [_serialize_observation_image(item) for item in records]
    return payload


@router.post("/identities/{identity_id}/maintenance", response_model=schemas.MaintenanceRecordOut)
def create_maintenance_record(
    identity_id: int,
    payload: schemas.MaintenanceRecordCreate,
    db: Session = Depends(get_db),
) -> models.MaintenanceRecord:
    identity = db.get(models.CrackIdentity, identity_id)
    if not identity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="裂缝身份档案不存在")

    record = models.MaintenanceRecord(
        identity_id=identity_id,
        action_type=payload.action_type,
        status=payload.status,
        priority_level=payload.priority_level,
        description=payload.description,
        repaired_by=payload.repaired_by,
        planned_at=payload.planned_at,
        completed_at=payload.completed_at,
        before_record_id=payload.before_record_id,
        after_record_id=payload.after_record_id,
        review_result=payload.review_result,
        review_notes=payload.review_notes,
    )
    db.add(record)
    if payload.status in {"completed", "repaired"}:
        identity.maintenance_status = "completed"
        identity.lifecycle_status = "repaired"
    elif payload.status in {"in_progress", "working"}:
        identity.maintenance_status = "in_progress"
    elif payload.status:
        identity.maintenance_status = payload.status
    db.commit()
    db.refresh(record)
    return record


@router.get("/{crack_id}", response_model=schemas.CrackRecordOut)
def get_crack_detail(crack_id: int, db: Session = Depends(get_db)) -> models.CrackRecord:
    record = db.get(models.CrackRecord, crack_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="裂缝记录不存在")
    return _serialize_crack_record(record)
