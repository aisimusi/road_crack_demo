from __future__ import annotations

import base64
from collections import Counter
from datetime import date, datetime, time, timedelta
from difflib import SequenceMatcher
import math
import mimetypes
from pathlib import Path
import re
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app import models
from app.database import UPLOADS_DIR
from app.services.geolocation import search_places, summarize_sensitive_pois

ROAD_ALIAS_HINTS = {
    "南门附近": "学府路",
    "南门": "学府路",
    "图书馆东路": "学府路",
    "图书馆东": "学府路",
    "校门口": "学府路",
    "图书馆": "学府路",
}
TIME_PHRASES = (
    "最近一周",
    "近7天",
    "近七天",
    "最近两周",
    "近14天",
    "本周",
    "上周",
    "最近一个月",
    "近30天",
    "本月",
    "上个月",
    "今天",
    "昨天",
)


class EmptyArgs(BaseModel):
    pass


class FindRoadArgs(BaseModel):
    road_name: str = Field(..., min_length=1, max_length=64)


class ParseTimeRangeArgs(BaseModel):
    text: str | None = Field(default=None, max_length=128)


class ResolveQueryContextArgs(BaseModel):
    query: str = Field(..., min_length=2, max_length=500)


class ResolvePlaceArgs(BaseModel):
    place_name: str = Field(..., min_length=1, max_length=128)
    city: str | None = Field(default=None, max_length=64)
    radius_m: int = Field(default=500, ge=50, le=5000)
    limit: int = Field(default=5, ge=1, le=10)


class QueryCracksArgs(BaseModel):
    road_name: str | None = Field(default=None, max_length=64)
    center_latitude: float | None = Field(default=None, ge=-90, le=90)
    center_longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_m: int | None = Field(default=None, ge=50, le=5000)
    start_date: str | None = Field(default=None, max_length=10)
    end_date: str | None = Field(default=None, max_length=10)
    severity_min: int | None = Field(default=None, ge=1, le=3)
    limit: int = Field(default=20, ge=1, le=100)
    order_by: str = Field(default="severity_desc", pattern="^(severity_desc|width_desc|length_desc|area_desc|time_desc|risk_desc)$")


class QueryCrackIdentitiesArgs(BaseModel):
    road_name: str | None = Field(default=None, max_length=64)
    center_latitude: float | None = Field(default=None, ge=-90, le=90)
    center_longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_m: int | None = Field(default=None, ge=50, le=5000)
    start_date: str | None = Field(default=None, max_length=10)
    end_date: str | None = Field(default=None, max_length=10)
    lifecycle_status: str | None = Field(default=None, max_length=32)
    maintenance_status: str | None = Field(default=None, max_length=32)
    unclosed_only: bool = False
    review_only: bool = False
    review_matched_existing_only: bool = True
    priority_level: str | None = Field(default=None, max_length=16)
    severity_min: int | None = Field(default=None, ge=1, le=3)
    area_growth_ratio_min: float | None = Field(default=None, ge=0.0, le=10.0)
    severity_growth_logic: str = Field(default="or", pattern="^(or|and)$")
    limit: int = Field(default=20, ge=1, le=100)
    order_by: str = Field(default="priority_desc", pattern="^(priority_desc|growth_desc|severity_desc|time_desc)$")


class CrackIdentityArgs(BaseModel):
    identity_id: int = Field(..., ge=1)


class AggregateCrackStatsArgs(BaseModel):
    road_name: str | None = Field(default=None, max_length=64)
    center_latitude: float | None = Field(default=None, ge=-90, le=90)
    center_longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_m: int | None = Field(default=None, ge=50, le=5000)
    start_date: str | None = Field(default=None, max_length=10)
    end_date: str | None = Field(default=None, max_length=10)


class CompareCrackStatsArgs(BaseModel):
    current_start: str = Field(..., min_length=10, max_length=10)
    current_end: str = Field(..., min_length=10, max_length=10)
    previous_start: str = Field(..., min_length=10, max_length=10)
    previous_end: str = Field(..., min_length=10, max_length=10)
    road_name: str | None = Field(default=None, max_length=64)
    center_latitude: float | None = Field(default=None, ge=-90, le=90)
    center_longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_m: int | None = Field(default=None, ge=50, le=5000)


class CrackIdsArgs(BaseModel):
    crack_ids: list[int] = Field(default_factory=list)


class GenerateMaintenanceAdviceArgs(BaseModel):
    stats: dict[str, Any] = Field(default_factory=dict)
    top_cracks: list[dict[str, Any]] = Field(default_factory=list)


class RankRoadsByRiskArgs(BaseModel):
    start_date: str | None = Field(default=None, max_length=10)
    end_date: str | None = Field(default=None, max_length=10)
    limit: int = Field(default=5, ge=1, le=50)


class AnalyzeSurroundingPoisArgs(BaseModel):
    crack_ids: list[int] = Field(default_factory=list)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_m: int = Field(default=300, ge=50, le=2000)
    max_points: int = Field(default=10, ge=1, le=20)


class AnalyzeCrackImagesArgs(BaseModel):
    crack_ids: list[int] = Field(default_factory=list)
    max_images: int = Field(default=3, ge=1, le=6)


class FindHighRiskCracksArgs(BaseModel):
    road_name: str | None = Field(default=None, max_length=64)
    center_latitude: float | None = Field(default=None, ge=-90, le=90)
    center_longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_m: int | None = Field(default=None, ge=50, le=5000)
    start_date: str | None = Field(default=None, max_length=10)
    end_date: str | None = Field(default=None, max_length=10)
    limit: int = Field(default=10, ge=1, le=50)


def today_local() -> date:
    return datetime.now().date()


def extract_time_phrase(text: str) -> str | None:
    normalized = text.strip()
    for phrase in TIME_PHRASES:
        if phrase in normalized:
            return phrase
    return None


def extract_road_hint(text: str) -> str | None:
    normalized = text.strip()
    for alias in sorted(ROAD_ALIAS_HINTS, key=len, reverse=True):
        if alias in normalized:
            return alias
    match = re.search(r"([\u4e00-\u9fa5]{2,16}(?:路|大道|街|巷|桥))", normalized)
    if match:
        return match.group(1)
    return None


def extract_landmark_hint(text: str) -> str | None:
    normalized = text.strip()
    for keyword in ("南门", "北门", "东门", "西门", "图书馆", "操场", "食堂", "宿舍", "教学楼", "实验楼"):
        if keyword in normalized:
            return keyword
    return None


def chinese_digit_to_int(text: str) -> int | None:
    mapping = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    if text in mapping:
        return mapping[text]
    return None


def _month_bounds(target: date) -> tuple[date, date]:
    month_start = target.replace(day=1)
    if month_start.month == 12:
        next_month = month_start.replace(year=month_start.year + 1, month=1, day=1)
    else:
        next_month = month_start.replace(month=month_start.month + 1, day=1)
    return month_start, next_month - timedelta(days=1)


def parse_relative_time_range(text: str | None, *, base_date: date | None = None) -> dict[str, str]:
    today = base_date or today_local()
    normalized = (text or "").strip()

    if not normalized:
        start = today - timedelta(days=7)
        return {
            "start_date": start.isoformat(),
            "end_date": today.isoformat(),
            "label": "最近7天",
        }

    iso_dates = re.findall(r"\d{4}-\d{2}-\d{2}", normalized)
    if len(iso_dates) >= 2:
        start = date.fromisoformat(iso_dates[0])
        end = date.fromisoformat(iso_dates[1])
        return {
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "label": f"{start.isoformat()}至{end.isoformat()}",
        }
    if len(iso_dates) == 1:
        only = date.fromisoformat(iso_dates[0])
        return {
            "start_date": only.isoformat(),
            "end_date": only.isoformat(),
            "label": only.isoformat(),
        }

    if normalized in {"最近一周", "近7天", "近七天"}:
        start = today - timedelta(days=7)
        return {"start_date": start.isoformat(), "end_date": today.isoformat(), "label": "最近7天"}
    if normalized in {"最近两周", "近14天"}:
        start = today - timedelta(days=14)
        return {"start_date": start.isoformat(), "end_date": today.isoformat(), "label": "最近14天"}
    if normalized in {"最近一个月", "近30天"}:
        start = today - timedelta(days=30)
        return {"start_date": start.isoformat(), "end_date": today.isoformat(), "label": "最近30天"}
    if normalized == "今天":
        return {"start_date": today.isoformat(), "end_date": today.isoformat(), "label": "今天"}
    if normalized == "昨天":
        yesterday = today - timedelta(days=1)
        return {"start_date": yesterday.isoformat(), "end_date": yesterday.isoformat(), "label": "昨天"}
    if normalized == "本周":
        monday = today - timedelta(days=today.weekday())
        return {"start_date": monday.isoformat(), "end_date": today.isoformat(), "label": "本周"}
    if normalized == "上周":
        this_monday = today - timedelta(days=today.weekday())
        last_sunday = this_monday - timedelta(days=1)
        last_monday = last_sunday - timedelta(days=6)
        return {"start_date": last_monday.isoformat(), "end_date": last_sunday.isoformat(), "label": "上周"}
    if normalized == "本月":
        start, end = _month_bounds(today)
        return {"start_date": start.isoformat(), "end_date": today.isoformat(), "label": "本月"}
    if normalized == "上个月":
        this_month_start = today.replace(day=1)
        previous_month_day = this_month_start - timedelta(days=1)
        start, end = _month_bounds(previous_month_day)
        return {"start_date": start.isoformat(), "end_date": end.isoformat(), "label": "上个月"}

    since_match = re.search(r"(\d{1,2})月以来", normalized)
    if since_match:
        month = max(1, min(12, int(since_match.group(1))))
        start = date(today.year, month, 1)
        return {"start_date": start.isoformat(), "end_date": today.isoformat(), "label": f"{month}月以来"}

    number_day_match = re.search(r"最近(\d{1,3})天", normalized)
    if number_day_match:
        days = max(1, min(365, int(number_day_match.group(1))))
        start = today - timedelta(days=days)
        return {"start_date": start.isoformat(), "end_date": today.isoformat(), "label": f"最近{days}天"}

    start = today - timedelta(days=7)
    return {"start_date": start.isoformat(), "end_date": today.isoformat(), "label": "最近7天"}


def week_comparison_ranges(*, base_date: date | None = None) -> dict[str, str]:
    today = base_date or today_local()
    this_monday = today - timedelta(days=today.weekday())
    last_sunday = this_monday - timedelta(days=1)
    last_monday = last_sunday - timedelta(days=6)
    return {
        "current_start": this_monday.isoformat(),
        "current_end": today.isoformat(),
        "previous_start": last_monday.isoformat(),
        "previous_end": last_sunday.isoformat(),
    }


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"日期格式错误，应为 YYYY-MM-DD: {value}") from exc


def _to_day_start(value: date) -> datetime:
    return datetime.combine(value, time.min)


def _to_day_end_exclusive(value: date) -> datetime:
    return datetime.combine(value + timedelta(days=1), time.min)


def _serialize_datetime(value: datetime | None) -> str | None:
    if not value:
        return None
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _resolve_upload_path(image_uri: str | None) -> Path | None:
    if not image_uri:
        return None
    normalized = str(image_uri).strip()
    if not normalized.startswith("/uploads/"):
        return None
    relative = normalized.removeprefix("/uploads/").lstrip("/")
    candidate = (UPLOADS_DIR / relative).resolve()
    try:
        candidate.relative_to(UPLOADS_DIR.resolve())
    except ValueError:
        return None
    return candidate if candidate.exists() and candidate.is_file() else None


def _file_to_data_url(path: Path) -> str:
    mime_type, _ = mimetypes.guess_type(path.name)
    mime_type = mime_type or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _round_risk_score(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _maintenance_level_from_grade(grade: str, *, has_severe: bool = False, max_width_mm: float = 0.0) -> tuple[str, str]:
    if grade == "差":
        return "一级", "立即维修"
    if grade == "次":
        return "二级", "优先维修"
    if grade == "中":
        if has_severe or max_width_mm >= 5.0:
            return "二级", "优先维修"
        return "三级", "计划维修"
    if grade == "良":
        return "三级", "计划维修"
    return "四级", "观察监测"


def _pci_to_technical_grade(pci: float) -> str:
    if pci >= 92:
        return "优"
    if pci >= 80:
        return "良"
    if pci >= 70:
        return "中"
    if pci >= 60:
        return "次"
    return "差"


def _estimate_reference_pci(
    *,
    severity_level: int,
    width_mm: float,
    length_m: float,
    area_m2: float,
    severity_score: float,
) -> float:
    base_deduction = {1: 7.0, 2: 18.0, 3: 34.0}.get(severity_level, 10.0)
    width_deduction = _clamp(width_mm, 0.0, 20.0) * 2.1
    length_deduction = min(length_m, 10.0) * 2.4
    area_deduction = min(area_m2 * 120.0, 26.0)
    model_deduction = _clamp(severity_score, 0.0, 1.0) * 10.0
    pci = 100.0 - (base_deduction + width_deduction + length_deduction + area_deduction + model_deduction)
    return round(_clamp(pci, 5.0, 98.0), 1)


def _estimate_reference_dr(reference_pci: float) -> float:
    if reference_pci >= 90:
        return round(max(0.1, (100.0 - reference_pci) * 0.2), 2)
    if reference_pci >= 80:
        return round(0.4 + (90.0 - reference_pci) * 0.16, 2)
    if reference_pci >= 70:
        return round(2.0 + (80.0 - reference_pci) * 0.35, 2)
    if reference_pci >= 60:
        return round(5.5 + (70.0 - reference_pci) * 0.55, 2)
    return round(11.0 + (60.0 - reference_pci) * 0.65, 2)


def _build_crack_standard_profile(
    record: models.CrackRecord,
    *,
    poi_exposure_score: float = 0.0,
) -> dict[str, Any]:
    width_mm = float(record.max_width_cm) * 10.0
    reference_pci = _estimate_reference_pci(
        severity_level=int(record.severity_level),
        width_mm=width_mm,
        length_m=float(record.length_m),
        area_m2=float(record.area_m2),
        severity_score=float(record.severity_score or 0.0),
    )
    reference_dr = _estimate_reference_dr(reference_pci)
    technical_grade = _pci_to_technical_grade(reference_pci)
    freshness_days = max((today_local() - record.detected_at.date()).days, 0)

    urgency_penalty = 0.0
    if freshness_days <= 3:
        urgency_penalty += 5.0
    elif freshness_days <= 7:
        urgency_penalty += 3.0
    elif freshness_days <= 15:
        urgency_penalty += 1.5

    urgency_penalty += min(float(poi_exposure_score) * 0.12, 10.0)
    risk_score = _round_risk_score(100.0 - reference_pci + urgency_penalty)
    maintenance_level, maintenance_label = _maintenance_level_from_grade(
        technical_grade,
        has_severe=int(record.severity_level) >= 3,
        max_width_mm=width_mm,
    )
    return {
        "reference_pci": reference_pci,
        "reference_dr": reference_dr,
        "technical_grade": technical_grade,
        "maintenance_level": maintenance_level,
        "maintenance_label": maintenance_label,
        "risk_score": risk_score,
    }


def _compute_crack_risk_score(record: models.CrackRecord, *, poi_exposure_score: float = 0.0) -> float:
    profile = _build_crack_standard_profile(record, poi_exposure_score=poi_exposure_score)
    return float(profile["risk_score"])


def _identity_area_growth_ratio(identity: models.CrackIdentity) -> float:
    current_area = float(identity.current_area_m2 or 0.0)
    growth_area = float(identity.growth_area_m2 or 0.0)
    previous_area = current_area - growth_area
    if previous_area <= 0:
        return 0.0
    return round(growth_area / previous_area, 4)


def _latest_review_record_for_identity(
    db: Session,
    identity_id: int,
    *,
    start_at: datetime | None,
    end_at_exclusive: datetime | None,
) -> models.CrackRecord | None:
    query = (
        db.query(models.CrackRecord)
        .join(models.InspectionTask, models.InspectionTask.id == models.CrackRecord.task_id)
        .filter(models.CrackRecord.identity_id == identity_id)
        .filter(models.InspectionTask.task_type.in_(("review", "reinspection")))
        .filter(models.InspectionTask.road_match_status == "matched_existing")
    )
    if start_at is not None:
        query = query.filter(models.CrackRecord.detected_at >= start_at)
    if end_at_exclusive is not None:
        query = query.filter(models.CrackRecord.detected_at < end_at_exclusive)
    return query.order_by(models.CrackRecord.detected_at.desc(), models.CrackRecord.id.desc()).first()


def _is_unclosed_maintenance_status(status: str | None) -> bool:
    normalized = (status or "").strip().lower()
    closed_values = {
        "closed",
        "completed",
        "complete",
        "finished",
        "done",
        "repaired",
        "resolved",
        "已闭环",
        "已完成",
        "已修复",
    }
    return normalized not in closed_values


def serialize_crack(
    record: models.CrackRecord,
    *,
    risk_score: float | None = None,
    distance_m: float | None = None,
) -> dict[str, Any]:
    standard_profile = _build_crack_standard_profile(record)
    computed_risk = standard_profile["risk_score"] if risk_score is None else risk_score
    item = {
        "id": record.id,
        "identity_id": record.identity_id,
        "identity_code": record.identity.identity_code if record.identity else None,
        "lifecycle_status": record.identity.lifecycle_status if record.identity else None,
        "maintenance_status": record.identity.maintenance_status if record.identity else None,
        "priority_level": record.identity.priority_level if record.identity else None,
        "crack_code": record.crack_code,
        "task_id": record.task_id,
        "road_name": record.road_name,
        "district": record.district,
        "crack_type": record.crack_type,
        "severity": record.severity_level,
        "severity_label": record.severity_label,
        "severity_score": round(float(record.severity_score), 2),
        "risk_score": computed_risk,
        "technical_grade": standard_profile["technical_grade"],
        "maintenance_level": standard_profile["maintenance_level"],
        "maintenance_label": standard_profile["maintenance_label"],
        "reference_pci": standard_profile["reference_pci"],
        "reference_dr": standard_profile["reference_dr"],
        "length_m": round(float(record.length_m), 2),
        "width_mm": round(float(record.avg_width_cm) * 10, 1),
        "max_width_mm": round(float(record.max_width_cm) * 10, 1),
        "area_m2": round(float(record.area_m2), 4),
        "lat": float(record.latitude),
        "lng": float(record.longitude),
        "image_url": record.result_image_uri or record.original_image_uri,
        "detected_at": _serialize_datetime(record.detected_at),
    }
    if distance_m is not None:
        item["distance_m"] = round(float(distance_m), 1)
    return item


def serialize_identity(identity: models.CrackIdentity) -> dict[str, Any]:
    return {
        "identity_id": identity.id,
        "identity_code": identity.identity_code,
        "road_name": identity.road_name,
        "district": identity.district,
        "crack_type": identity.crack_type,
        "lifecycle_status": identity.lifecycle_status,
        "maintenance_status": identity.maintenance_status,
        "priority_level": identity.priority_level,
        "observation_count": int(identity.observation_count or 0),
        "first_seen_at": _serialize_datetime(identity.first_seen_at),
        "last_seen_at": _serialize_datetime(identity.last_seen_at),
        "severity_level": int(identity.current_severity_level or 0),
        "severity_label": identity.current_severity_label,
        "severity_score": round(float(identity.current_severity_score or 0.0), 2),
        "length_m": round(float(identity.current_length_m or 0.0), 2),
        "width_mm": round(float(identity.current_avg_width_cm or 0.0) * 10.0, 1),
        "max_width_mm": round(float(identity.current_max_width_cm or 0.0) * 10.0, 1),
        "area_m2": round(float(identity.current_area_m2 or 0.0), 4),
        "max_area_m2": round(float(identity.max_area_m2 or 0.0), 4),
        "growth_area_m2": round(float(identity.growth_area_m2 or 0.0), 4),
        "growth_length_m": round(float(identity.growth_length_m or 0.0), 3),
        "lat": float(identity.latest_latitude),
        "lng": float(identity.latest_longitude),
        "image_url": identity.latest_result_image_uri or identity.latest_original_image_uri,
        "remark": identity.remark,
    }


def serialize_identity_for_agent(
    db: Session,
    identity: models.CrackIdentity,
    *,
    distance_m: float | None = None,
) -> dict[str, Any]:
    latest_record = (
        db.query(models.CrackRecord)
        .filter(models.CrackRecord.identity_id == identity.id)
        .order_by(models.CrackRecord.detected_at.desc())
        .first()
    )
    item = serialize_identity(identity)
    item["id"] = latest_record.id if latest_record else identity.id
    item["latest_record_id"] = latest_record.id if latest_record else None
    item["identity_id"] = identity.id
    item["crack_code"] = latest_record.crack_code if latest_record else identity.identity_code
    item["area_growth_ratio"] = _identity_area_growth_ratio(identity)
    if distance_m is not None:
        item["distance_m"] = round(float(distance_m), 1)
    return item


def _load_known_roads(db: Session) -> list[dict[str, Any]]:
    roads: list[dict[str, Any]] = []
    seen: set[str] = set()

    segments = db.query(models.RoadSegment).order_by(models.RoadSegment.road_name.asc()).all()
    for segment in segments:
        if segment.road_name in seen:
            continue
        seen.add(segment.road_name)
        roads.append(
            {
                "id": segment.id,
                "name": segment.road_name,
                "district": segment.district,
                "center_latitude": segment.center_latitude,
                "center_longitude": segment.center_longitude,
                "lane_count": segment.lane_count,
                "road_length_km": segment.road_length_km,
            }
        )

    crack_rows = (
        db.query(models.CrackRecord.road_name, models.CrackRecord.district)
        .distinct()
        .order_by(models.CrackRecord.road_name.asc())
        .all()
    )
    synthetic_id = 100000
    for row in crack_rows:
        if row.road_name in seen:
            continue
        seen.add(row.road_name)
        roads.append(
            {
                "id": synthetic_id,
                "name": row.road_name,
                "district": row.district,
                "center_latitude": None,
                "center_longitude": None,
                "lane_count": None,
                "road_length_km": None,
            }
        )
        synthetic_id += 1

    return roads


def _resolve_road_name(db: Session, road_name: str) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]]]:
    roads = _load_known_roads(db)
    requested = road_name.strip()
    alias_target = ROAD_ALIAS_HINTS.get(requested, requested)
    for item in roads:
        if item["name"] == alias_target:
            return item["name"], item, []

    exact_substring = [item for item in roads if requested in item["name"] or item["name"] in requested]
    if exact_substring:
        return exact_substring[0]["name"], exact_substring[0], exact_substring[1:4]

    scored = []
    for item in roads:
        score = SequenceMatcher(None, requested, item["name"]).ratio()
        if score >= 0.35:
            scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    candidates = [item for _, item in scored[:5]]
    return alias_target, None, candidates


def _resolve_landmark_to_road(db: Session, landmark: str) -> dict[str, Any] | None:
    candidates = search_places(landmark, limit=5)
    roads = _load_known_roads(db)
    if not candidates:
        alias = ROAD_ALIAS_HINTS.get(landmark)
        if alias:
            _, road, _ = _resolve_road_name(db, alias)
            return road
        return None

    place_names = [candidate.name for candidate in candidates]
    for candidate in candidates:
        for road in roads:
            if road["name"] in candidate.name or road["name"] in (candidate.address or ""):
                return road

    alias = ROAD_ALIAS_HINTS.get(landmark)
    if alias:
        _, road, _ = _resolve_road_name(db, alias)
        return road

    for place_name in place_names:
        resolved_name, road, _ = _resolve_road_name(db, place_name)
        if road and resolved_name:
            return road
    return None


def _extract_radius_m(text: str, default: int = 500) -> int:
    normalized = text.strip()
    match = re.search(r"(?:附近|周边|周围|范围内)?\s*(\d{2,4})\s*米", normalized)
    if match:
        return max(50, min(5000, int(match.group(1))))
    km_match = re.search(r"(?:附近|周边|周围|范围内)?\s*(\d+(?:\.\d+)?)\s*(?:公里|千米|km)", normalized, re.IGNORECASE)
    if km_match:
        return max(50, min(5000, int(float(km_match.group(1)) * 1000)))
    return default


def _extract_place_hint(text: str) -> str | None:
    normalized = text.strip()
    patterns = (
        r"([\u4e00-\u9fa5A-Za-z0-9·（）()]{2,40}?)(?:附近|周边|周围|周边范围|周边区域|范围内)\s*\d*(?:\.\d+)?\s*(?:米|公里|千米|km)?",
        r"距离([\u4e00-\u9fa5A-Za-z0-9·（）()]{2,40}?)(?:\d*(?:\.\d+)?\s*(?:米|公里|千米|km))?范围",
    )
    stop_prefixes = (
        "帮我找出",
        "查询",
        "查看",
        "统计",
        "分析",
        "请",
        "请帮我",
        "找出",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if not match:
            continue
        candidate = match.group(1).strip(" ，,。的在于")
        for prefix in stop_prefixes:
            if candidate.startswith(prefix):
                candidate = candidate.removeprefix(prefix).strip(" ，,。的在于")
        if candidate and not re.search(r"(?:路|大道|街|巷|桥)$", candidate):
            return candidate
    return None


def _place_candidate_to_dict(candidate, *, radius_m: int) -> dict[str, Any]:
    return {
        "name": candidate.name,
        "address": candidate.address,
        "district": candidate.district,
        "city": candidate.city,
        "province": candidate.province,
        "longitude": candidate.longitude,
        "latitude": candidate.latitude,
        "radius_m": radius_m,
        "type_name": candidate.type_name,
        "distance": candidate.distance,
        "source": candidate.source,
    }


def _distance_between_points_m(
    longitude: float,
    latitude: float,
    center_longitude: float,
    center_latitude: float,
) -> float:
    lat_scale = 111_320.0
    lon_scale = 111_320.0 * math.cos(math.radians((latitude + center_latitude) / 2))
    return math.hypot((longitude - center_longitude) * lon_scale, (latitude - center_latitude) * lat_scale)


def _has_radius_filter(
    *,
    center_latitude: float | None,
    center_longitude: float | None,
    radius_m: int | None,
) -> bool:
    provided = [center_latitude is not None, center_longitude is not None, radius_m is not None]
    if any(provided) and not all(provided):
        raise ValueError("按地点半径查询时需要同时提供 center_latitude、center_longitude 和 radius_m。")
    return all(provided)


def _row_distance_m(
    row: models.CrackRecord | models.CrackIdentity,
    *,
    center_latitude: float,
    center_longitude: float,
) -> float:
    longitude = getattr(row, "longitude", None)
    latitude = getattr(row, "latitude", None)
    if longitude is None or latitude is None:
        longitude = getattr(row, "latest_longitude", None)
        latitude = getattr(row, "latest_latitude", None)
    return _distance_between_points_m(
        float(longitude),
        float(latitude),
        float(center_longitude),
        float(center_latitude),
    )


def _filter_rows_by_radius(
    rows: list[models.CrackRecord],
    *,
    center_latitude: float | None,
    center_longitude: float | None,
    radius_m: int | None,
) -> list[tuple[models.CrackRecord, float | None]]:
    if not _has_radius_filter(
        center_latitude=center_latitude,
        center_longitude=center_longitude,
        radius_m=radius_m,
    ):
        return [(row, None) for row in rows]
    assert center_latitude is not None
    assert center_longitude is not None
    assert radius_m is not None
    result: list[tuple[models.CrackRecord, float | None]] = []
    for row in rows:
        distance = _row_distance_m(row, center_latitude=center_latitude, center_longitude=center_longitude)
        if distance <= radius_m:
            result.append((row, round(distance, 1)))
    return result


def _filter_identities_by_radius(
    rows: list[models.CrackIdentity],
    *,
    center_latitude: float | None,
    center_longitude: float | None,
    radius_m: int | None,
) -> list[tuple[models.CrackIdentity, float | None]]:
    if not _has_radius_filter(
        center_latitude=center_latitude,
        center_longitude=center_longitude,
        radius_m=radius_m,
    ):
        return [(row, None) for row in rows]
    assert center_latitude is not None
    assert center_longitude is not None
    assert radius_m is not None
    result: list[tuple[models.CrackIdentity, float | None]] = []
    for row in rows:
        distance = _row_distance_m(row, center_latitude=center_latitude, center_longitude=center_longitude)
        if distance <= radius_m:
            result.append((row, round(distance, 1)))
    return result


def _spatial_context(
    *,
    center_latitude: float | None,
    center_longitude: float | None,
    radius_m: int | None,
) -> dict[str, Any] | None:
    if not _has_radius_filter(
        center_latitude=center_latitude,
        center_longitude=center_longitude,
        radius_m=radius_m,
    ):
        return None
    return {
        "center_latitude": center_latitude,
        "center_longitude": center_longitude,
        "radius_m": radius_m,
    }


def _build_crack_query(
    db: Session,
    *,
    road_name: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    severity_min: int | None = None,
):
    query = db.query(models.CrackRecord)
    resolved_road_name: str | None = None

    if road_name:
        resolved_road_name, matched, candidates = _resolve_road_name(db, road_name)
        if not matched:
            candidate_names = "、".join(item["name"] for item in candidates) if candidates else "暂无候选道路"
            raise ValueError(f"未找到道路“{road_name}”，候选道路：{candidate_names}")
        query = query.filter(models.CrackRecord.road_name == resolved_road_name)

    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if start and end and start > end:
        raise ValueError("开始日期不能晚于结束日期。")
    if start:
        query = query.filter(models.CrackRecord.detected_at >= _to_day_start(start))
    if end:
        query = query.filter(models.CrackRecord.detected_at < _to_day_end_exclusive(end))
    if severity_min is not None:
        query = query.filter(models.CrackRecord.severity_level >= severity_min)

    return query, resolved_road_name


def _compute_stats_from_rows(rows: list[models.CrackRecord]) -> dict[str, Any]:
    counter = Counter(row.severity_label for row in rows)
    total_length = sum(float(row.length_m) for row in rows)
    total_area = sum(float(row.area_m2) for row in rows)
    max_width_mm = max((float(row.max_width_cm) * 10 for row in rows), default=0.0)
    avg_width_mm = (sum(float(row.avg_width_cm) * 10 for row in rows) / len(rows)) if rows else 0.0
    profiles = [_build_crack_standard_profile(row) for row in rows]
    avg_risk_score = (sum(float(profile["risk_score"]) for profile in profiles) / len(profiles)) if profiles else 0.0
    avg_reference_pci = (sum(float(profile["reference_pci"]) for profile in profiles) / len(profiles)) if profiles else 100.0
    avg_reference_dr = (sum(float(profile["reference_dr"]) for profile in profiles) / len(profiles)) if profiles else 0.0
    road_counter = Counter(row.road_name for row in rows)
    road_distribution = [
        {"road_name": name, "count": count}
        for name, count in sorted(road_counter.items(), key=lambda item: (-item[1], item[0]))
    ]
    technical_grade = _pci_to_technical_grade(avg_reference_pci) if rows else "优"
    maintenance_level, maintenance_label = _maintenance_level_from_grade(
        technical_grade,
        has_severe=counter.get("严重", 0) > 0,
        max_width_mm=max_width_mm,
    )
    return {
        "total_count": len(rows),
        "severe_count": counter.get("严重", 0),
        "medium_count": counter.get("中等", 0),
        "minor_count": counter.get("轻微", 0),
        "severity_distribution": {
            "轻微": counter.get("轻微", 0),
            "中等": counter.get("中等", 0),
            "严重": counter.get("严重", 0),
        },
        "total_length_m": round(total_length, 2),
        "total_area_m2": round(total_area, 4),
        "max_width_mm": round(max_width_mm, 1),
        "avg_width_mm": round(avg_width_mm, 1),
        "avg_risk_score": _round_risk_score(avg_risk_score),
        "reference_pci": round(avg_reference_pci, 1),
        "reference_dr": round(avg_reference_dr, 2),
        "technical_grade": technical_grade,
        "maintenance_level": maintenance_level,
        "maintenance_label": maintenance_label,
        "road_distribution": road_distribution,
        "standard_basis": "参考 JTG 5210-2018 的 PCI/DR 对应关系与技术状况等级阈值推导。",
    }


def inspect_schema_tool(_: Session, __: EmptyArgs) -> dict[str, Any]:
    return {
        "tables": [
            {
                "name": "road_segment",
                "description": "道路基础信息表",
                "fields": [
                    {"name": "road_name", "description": "道路名称"},
                    {"name": "district", "description": "所属区域"},
                    {"name": "center_longitude", "description": "道路中心经度"},
                    {"name": "center_latitude", "description": "道路中心纬度"},
                    {"name": "lane_count", "description": "车道数"},
                    {"name": "road_length_km", "description": "道路长度"},
                ],
            },
            {
                "name": "inspection_task",
                "description": "巡检任务表",
                "fields": [
                    {"name": "task_name", "description": "任务名称"},
                    {"name": "road_name", "description": "巡检道路"},
                    {"name": "status", "description": "任务状态"},
                    {"name": "finished_at", "description": "任务完成时间"},
                ],
            },
            {
                "name": "crack_record",
                "description": "裂缝观测记录表，一条记录代表一次巡检中的一次检测结果",
                "fields": [
                    {"name": "id", "description": "裂缝ID"},
                    {"name": "identity_id", "description": "裂缝单体身份档案ID"},
                    {"name": "road_name", "description": "道路名称"},
                    {"name": "severity_level", "description": "严重等级，1=轻微，2=中等，3=严重"},
                    {"name": "severity_score", "description": "模型原始严重度分数"},
                    {"name": "length_m", "description": "裂缝长度，单位米"},
                    {"name": "avg_width_cm", "description": "平均宽度，单位厘米"},
                    {"name": "max_width_cm", "description": "最大宽度，单位厘米"},
                    {"name": "area_m2", "description": "裂缝面积，单位平方米"},
                    {"name": "longitude", "description": "经度"},
                    {"name": "latitude", "description": "纬度"},
                    {"name": "detected_at", "description": "检测时间"},
                    {"name": "result_image_uri", "description": "结果图片路径"},
                ],
            },
            {
                "name": "crack_identity",
                "description": "裂缝单体身份档案表，用于跨批次追踪同一条裂缝",
                "fields": [
                    {"name": "identity_code", "description": "裂缝身份编号"},
                    {"name": "lifecycle_status", "description": "生命周期状态，如 active/repaired/recurred"},
                    {"name": "maintenance_status", "description": "维修状态"},
                    {"name": "priority_level", "description": "处置优先级"},
                    {"name": "observation_count", "description": "累计观测次数"},
                    {"name": "growth_area_m2", "description": "最近一次面积变化"},
                    {"name": "growth_length_m", "description": "最近一次长度变化"},
                    {"name": "last_seen_at", "description": "最近观测时间"},
                ],
            },
            {
                "name": "maintenance_record",
                "description": "维修处置和复检记录表，挂接到裂缝身份档案",
                "fields": [
                    {"name": "identity_id", "description": "裂缝身份档案ID"},
                    {"name": "action_type", "description": "处置类型"},
                    {"name": "status", "description": "处置状态"},
                    {"name": "review_result", "description": "复检结果"},
                    {"name": "completed_at", "description": "完成时间"},
                ],
            },
        ],
        "notes": [
            "当前版本采用参数化工具调用，不允许 LLM 直接执行 SQL。",
            "风险评分由裂缝严重等级、宽度、长度、面积、时效性和周边敏感设施共同估计。",
        ],
    }


def list_roads_tool(db: Session, _: EmptyArgs) -> dict[str, Any]:
    roads = _load_known_roads(db)
    return {"roads": roads, "count": len(roads)}


def find_road_tool(db: Session, args: FindRoadArgs) -> dict[str, Any]:
    requested = args.road_name.strip()
    resolved_name, road, candidates = _resolve_road_name(db, requested)
    if road:
        message = "已匹配道路。"
        if requested in ROAD_ALIAS_HINTS:
            message = f"已将“{requested}”映射为道路“{resolved_name}”。"
        return {
            "matched": True,
            "road": road,
            "candidates": candidates,
            "message": message,
        }

    landmark_road = _resolve_landmark_to_road(db, requested)
    if landmark_road:
        return {
            "matched": True,
            "road": landmark_road,
            "candidates": candidates,
            "message": f"已根据地标“{requested}”关联到道路“{landmark_road['name']}”。",
        }

    return {
        "matched": False,
        "road": None,
        "candidates": candidates,
        "message": f"未找到完全匹配道路“{requested}”，请参考候选道路。",
    }


def parse_time_range_tool(_: Session, args: ParseTimeRangeArgs) -> dict[str, Any]:
    return parse_relative_time_range(args.text)


def _local_place_fallback(db: Session, place_name: str, *, radius_m: int, limit: int) -> list[dict[str, Any]]:
    normalized = place_name.strip()
    candidates: list[dict[str, Any]] = []
    for road in _load_known_roads(db):
        if normalized not in road["name"] and road["name"] not in normalized:
            continue
        longitude = road.get("center_longitude")
        latitude = road.get("center_latitude")
        if longitude is None or latitude is None:
            records = (
                db.query(models.CrackRecord)
                .filter(models.CrackRecord.road_name == road["name"])
                .order_by(models.CrackRecord.detected_at.desc())
                .limit(20)
                .all()
            )
            if records:
                longitude = sum(float(row.longitude) for row in records) / len(records)
                latitude = sum(float(row.latitude) for row in records) / len(records)
        if longitude is None or latitude is None:
            continue
        candidates.append(
            {
                "name": road["name"],
                "address": f"{road.get('district') or ''}{road['name']}",
                "district": road.get("district"),
                "city": None,
                "province": None,
                "longitude": float(longitude),
                "latitude": float(latitude),
                "radius_m": radius_m,
                "type_name": "本地道路中心",
                "distance": None,
                "source": "local.road_center",
            }
        )
    return candidates[:limit]


def resolve_place_tool(db: Session, args: ResolvePlaceArgs) -> dict[str, Any]:
    candidates = search_places(args.place_name, city=args.city, limit=args.limit)
    items = [
        _place_candidate_to_dict(candidate, radius_m=args.radius_m)
        for candidate in candidates
        if candidate.longitude is not None and candidate.latitude is not None
    ]
    if not items:
        items = _local_place_fallback(db, args.place_name, radius_m=args.radius_m, limit=args.limit)
    selected = items[0] if items else None
    return {
        "matched": bool(selected),
        "requested": args.place_name,
        "radius_m": args.radius_m,
        "selected": selected,
        "candidates": items,
        "message": (
            f"已解析地点“{args.place_name}”，可按中心点周边 {args.radius_m} 米查询。"
            if selected
            else f"未能解析地点“{args.place_name}”，请换用更具体的地名或道路名。"
        ),
    }


def resolve_query_context_tool(db: Session, args: ResolveQueryContextArgs) -> dict[str, Any]:
    query = args.query.strip()
    time_result = parse_relative_time_range(extract_time_phrase(query) or query)
    road_hint = extract_road_hint(query)
    landmark_hint = extract_landmark_hint(query)
    place_hint = _extract_place_hint(query)
    radius_m = _extract_radius_m(query)

    road_match: dict[str, Any] | None = None
    if road_hint:
        resolved_name, road, candidates = _resolve_road_name(db, road_hint)
        road_match = {
            "matched": bool(road),
            "requested": road_hint,
            "resolved_name": resolved_name,
            "road": road,
            "candidates": candidates,
        }
    elif landmark_hint:
        landmark_road = _resolve_landmark_to_road(db, landmark_hint)
        road_match = {
            "matched": bool(landmark_road),
            "requested": landmark_hint,
            "resolved_name": (landmark_road or {}).get("name"),
            "road": landmark_road,
            "candidates": [],
        }

    place_match: dict[str, Any] | None = None
    if place_hint and not road_hint:
        place_match = resolve_place_tool(
            db,
            ResolvePlaceArgs(place_name=place_hint, radius_m=radius_m),
        )

    return {
        "query": query,
        "time_range": time_result,
        "road_hint": road_hint,
        "landmark_hint": landmark_hint,
        "place_hint": place_hint,
        "radius_m": radius_m,
        "road_match": road_match,
        "place_match": place_match,
        "message": "已完成查询上下文解析。",
    }


def query_cracks_tool(db: Session, args: QueryCracksArgs) -> dict[str, Any]:
    query, resolved_road_name = _build_crack_query(
        db,
        road_name=args.road_name,
        start_date=args.start_date,
        end_date=args.end_date,
        severity_min=args.severity_min,
    )
    spatial = _spatial_context(
        center_latitude=args.center_latitude,
        center_longitude=args.center_longitude,
        radius_m=args.radius_m,
    )

    if args.order_by == "width_desc":
        query = query.order_by(models.CrackRecord.max_width_cm.desc(), models.CrackRecord.detected_at.desc())
    elif args.order_by == "length_desc":
        query = query.order_by(models.CrackRecord.length_m.desc(), models.CrackRecord.detected_at.desc())
    elif args.order_by == "area_desc":
        query = query.order_by(models.CrackRecord.area_m2.desc(), models.CrackRecord.detected_at.desc())
    elif args.order_by == "time_desc":
        query = query.order_by(models.CrackRecord.detected_at.desc(), models.CrackRecord.severity_level.desc())
    elif args.order_by == "risk_desc":
        rows = query.all()
        rows_with_distance = _filter_rows_by_radius(
            rows,
            center_latitude=args.center_latitude,
            center_longitude=args.center_longitude,
            radius_m=args.radius_m,
        )
        enriched = sorted(rows_with_distance, key=lambda item: _compute_crack_risk_score(item[0]), reverse=True)
        selected = enriched[: args.limit]
        items = [serialize_crack(row, distance_m=distance) for row, distance in selected]
        return {
            "items": items,
            "count": len(items),
            "road_name": resolved_road_name,
            "spatial_filter": spatial,
            "start_date": args.start_date,
            "end_date": args.end_date,
            "order_by": args.order_by,
            "message": f"已按综合风险排序返回 {len(items)} 条裂缝记录。",
        }
    else:
        query = query.order_by(
            models.CrackRecord.severity_level.desc(),
            models.CrackRecord.max_width_cm.desc(),
            models.CrackRecord.detected_at.desc(),
        )

    rows = query.all() if spatial else query.limit(args.limit).all()
    rows_with_distance = _filter_rows_by_radius(
        rows,
        center_latitude=args.center_latitude,
        center_longitude=args.center_longitude,
        radius_m=args.radius_m,
    )
    selected = rows_with_distance[: args.limit]
    items = [serialize_crack(row, distance_m=distance) for row, distance in selected]
    if not items:
        return {
            "items": [],
            "count": 0,
            "road_name": resolved_road_name,
            "spatial_filter": spatial,
            "start_date": args.start_date,
            "end_date": args.end_date,
            "order_by": args.order_by,
            "message": "未查询到相关裂缝记录。",
        }
    return {
        "items": items,
        "count": len(items),
        "road_name": resolved_road_name,
        "spatial_filter": spatial,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "order_by": args.order_by,
        "message": f"已查询到 {len(items)} 条裂缝记录。",
    }


def query_crack_identities_tool(db: Session, args: QueryCrackIdentitiesArgs) -> dict[str, Any]:
    query = db.query(models.CrackIdentity)
    resolved_road_name = None
    spatial = _spatial_context(
        center_latitude=args.center_latitude,
        center_longitude=args.center_longitude,
        radius_m=args.radius_m,
    )
    if args.road_name:
        resolved_road_name, matched, candidates = _resolve_road_name(db, args.road_name)
        if not matched:
            candidate_names = "、".join(item["name"] for item in candidates) if candidates else "暂无候选道路"
            raise ValueError(f"未找到道路“{args.road_name}”，候选道路：{candidate_names}")
        query = query.filter(models.CrackIdentity.road_name == resolved_road_name)
    if args.lifecycle_status:
        query = query.filter(models.CrackIdentity.lifecycle_status == args.lifecycle_status)
    if args.maintenance_status:
        query = query.filter(models.CrackIdentity.maintenance_status == args.maintenance_status)
    if args.unclosed_only:
        query = query.filter(~models.CrackIdentity.maintenance_status.in_((
            "closed",
            "completed",
            "complete",
            "finished",
            "done",
            "repaired",
            "resolved",
            "已闭环",
            "已完成",
            "已修复",
        )))
    if args.priority_level:
        query = query.filter(models.CrackIdentity.priority_level == args.priority_level)

    start = _parse_date(args.start_date)
    end = _parse_date(args.end_date)
    if start and end and start > end:
        raise ValueError("开始日期不能晚于结束日期。")
    start_at = _to_day_start(start) if start else None
    end_at_exclusive = _to_day_end_exclusive(end) if end else None
    if start_at is not None:
        query = query.filter(models.CrackIdentity.last_seen_at >= start_at)
    if end_at_exclusive is not None:
        query = query.filter(models.CrackIdentity.last_seen_at < end_at_exclusive)
    if args.review_only:
        query = query.join(
            models.CrackRecord,
            models.CrackRecord.identity_id == models.CrackIdentity.id,
        ).join(
            models.InspectionTask,
            models.InspectionTask.id == models.CrackRecord.task_id,
        ).filter(models.InspectionTask.task_type.in_(("review", "reinspection")))
        if args.review_matched_existing_only:
            query = query.filter(models.InspectionTask.road_match_status == "matched_existing")
        if start_at is not None:
            query = query.filter(models.CrackRecord.detected_at >= start_at)
        if end_at_exclusive is not None:
            query = query.filter(models.CrackRecord.detected_at < end_at_exclusive)
        query = query.distinct()

    if args.severity_min is not None and args.area_growth_ratio_min is not None:
        severity_matches = models.CrackIdentity.current_severity_level >= args.severity_min
        growth_matches = models.CrackIdentity.growth_area_m2 > (
            (models.CrackIdentity.current_area_m2 - models.CrackIdentity.growth_area_m2)
            * args.area_growth_ratio_min
        )
        if args.severity_growth_logic == "and":
            query = query.filter(severity_matches).filter(growth_matches)
        else:
            query = query.filter(severity_matches | growth_matches)
    elif args.severity_min is not None:
        query = query.filter(models.CrackIdentity.current_severity_level >= args.severity_min)
    elif args.area_growth_ratio_min is not None:
        query = query.filter(
            models.CrackIdentity.growth_area_m2 > (
                (models.CrackIdentity.current_area_m2 - models.CrackIdentity.growth_area_m2)
                * args.area_growth_ratio_min
            )
        )

    if args.order_by == "growth_desc":
        query = query.order_by(models.CrackIdentity.growth_area_m2.desc(), models.CrackIdentity.last_seen_at.desc())
    elif args.order_by == "severity_desc":
        query = query.order_by(models.CrackIdentity.current_severity_level.desc(), models.CrackIdentity.last_seen_at.desc())
    elif args.order_by == "time_desc":
        query = query.order_by(models.CrackIdentity.last_seen_at.desc())
    else:
        priority_rank = {"高": 3, "中": 2, "低": 1}
        rows = query.all()
        rows_with_distance = _filter_identities_by_radius(
            rows,
            center_latitude=args.center_latitude,
            center_longitude=args.center_longitude,
            radius_m=args.radius_m,
        )
        rows_with_distance.sort(
            key=lambda item: (
                -priority_rank.get(item[0].priority_level, 0),
                -int(item[0].current_severity_level or 0),
                -(item[0].last_seen_at.timestamp() if item[0].last_seen_at else 0),
            )
        )
        selected = rows_with_distance[: args.limit]
        items = [serialize_identity_for_agent(db, row, distance_m=distance) for row, distance in selected]
        return {
            "items": items,
            "count": len(items),
            "road_name": resolved_road_name,
            "spatial_filter": spatial,
            "start_date": args.start_date,
            "end_date": args.end_date,
            "review_only": args.review_only,
            "unclosed_only": args.unclosed_only,
            "severity_min": args.severity_min,
            "area_growth_ratio_min": args.area_growth_ratio_min,
            "severity_growth_logic": args.severity_growth_logic,
            "message": f"已返回 {len(items)} 条裂缝身份档案。",
        }

    rows = query.all() if spatial else query.limit(args.limit).all()
    rows_with_distance = _filter_identities_by_radius(
        rows,
        center_latitude=args.center_latitude,
        center_longitude=args.center_longitude,
        radius_m=args.radius_m,
    )
    selected = rows_with_distance[: args.limit]
    items = [serialize_identity_for_agent(db, row, distance_m=distance) for row, distance in selected]
    return {
        "items": items,
        "count": len(items),
        "road_name": resolved_road_name,
        "spatial_filter": spatial,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "review_only": args.review_only,
        "unclosed_only": args.unclosed_only,
        "severity_min": args.severity_min,
        "area_growth_ratio_min": args.area_growth_ratio_min,
        "severity_growth_logic": args.severity_growth_logic,
        "message": f"已返回 {len(items)} 条裂缝身份档案。",
    }


def get_crack_identity_timeline_tool(db: Session, args: CrackIdentityArgs) -> dict[str, Any]:
    identity = db.get(models.CrackIdentity, args.identity_id)
    if not identity:
        raise ValueError("裂缝身份档案不存在。")

    records = (
        db.query(models.CrackRecord)
        .filter(models.CrackRecord.identity_id == args.identity_id)
        .order_by(models.CrackRecord.detected_at.asc())
        .all()
    )
    maintenance_records = (
        db.query(models.MaintenanceRecord)
        .filter(models.MaintenanceRecord.identity_id == args.identity_id)
        .order_by(models.MaintenanceRecord.created_at.asc())
        .all()
    )
    timeline = []
    for row in records:
        timeline.append(
            {
                "type": "observation",
                "record_id": row.id,
                "task_id": row.task_id,
                "detected_at": _serialize_datetime(row.detected_at),
                "severity_label": row.severity_label,
                "length_m": round(float(row.length_m), 2),
                "area_m2": round(float(row.area_m2), 4),
                "max_width_mm": round(float(row.max_width_cm) * 10.0, 1),
            }
        )
    for row in maintenance_records:
        timeline.append(
            {
                "type": "maintenance",
                "maintenance_id": row.id,
                "action_type": row.action_type,
                "status": row.status,
                "priority_level": row.priority_level,
                "completed_at": _serialize_datetime(row.completed_at),
                "review_result": row.review_result,
                "description": row.description,
            }
        )
    timeline.sort(key=lambda item: item.get("detected_at") or item.get("completed_at") or "")
    return {
        "identity": serialize_identity(identity),
        "timeline": timeline,
        "observation_count": len(records),
        "maintenance_count": len(maintenance_records),
        "message": "已返回裂缝身份档案的观测、维修和复检时间线。",
    }


def aggregate_crack_stats_tool(db: Session, args: AggregateCrackStatsArgs) -> dict[str, Any]:
    query, resolved_road_name = _build_crack_query(
        db,
        road_name=args.road_name,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    rows = query.order_by(models.CrackRecord.detected_at.desc()).all()
    rows = [
        row
        for row, _ in _filter_rows_by_radius(
            rows,
            center_latitude=args.center_latitude,
            center_longitude=args.center_longitude,
            radius_m=args.radius_m,
        )
    ]
    stats = _compute_stats_from_rows(rows)
    stats["road_name"] = resolved_road_name
    stats["spatial_filter"] = _spatial_context(
        center_latitude=args.center_latitude,
        center_longitude=args.center_longitude,
        radius_m=args.radius_m,
    )
    stats["start_date"] = args.start_date
    stats["end_date"] = args.end_date
    stats["message"] = "未查询到相关裂缝记录。" if not rows else f"已完成 {len(rows)} 条裂缝的统计分析。"
    return stats


def compare_crack_stats_tool(db: Session, args: CompareCrackStatsArgs) -> dict[str, Any]:
    current_rows = _build_crack_query(
        db,
        road_name=args.road_name,
        start_date=args.current_start,
        end_date=args.current_end,
    )[0].all()
    previous_rows = _build_crack_query(
        db,
        road_name=args.road_name,
        start_date=args.previous_start,
        end_date=args.previous_end,
    )[0].all()
    current_rows = [
        row
        for row, _ in _filter_rows_by_radius(
            current_rows,
            center_latitude=args.center_latitude,
            center_longitude=args.center_longitude,
            radius_m=args.radius_m,
        )
    ]
    previous_rows = [
        row
        for row, _ in _filter_rows_by_radius(
            previous_rows,
            center_latitude=args.center_latitude,
            center_longitude=args.center_longitude,
            radius_m=args.radius_m,
        )
    ]

    current = _compute_stats_from_rows(current_rows)
    previous = _compute_stats_from_rows(previous_rows)
    previous_count = previous["total_count"]
    current_count = current["total_count"]
    count_change = current_count - previous_count
    if previous_count == 0:
        count_change_rate = None if current_count == 0 else 1.0
    else:
        count_change_rate = round(count_change / previous_count, 4)

    return {
        "current": current,
        "previous": previous,
        "delta": {
            "count_change": count_change,
            "count_change_rate": count_change_rate,
            "serious_count_change": current["severe_count"] - previous["severe_count"],
            "length_change_m": round(current["total_length_m"] - previous["total_length_m"], 2),
            "area_change_m2": round(current["total_area_m2"] - previous["total_area_m2"], 4),
            "avg_risk_change": round(current["avg_risk_score"] - previous["avg_risk_score"], 1),
        },
        "road_name": args.road_name,
        "spatial_filter": _spatial_context(
            center_latitude=args.center_latitude,
            center_longitude=args.center_longitude,
            radius_m=args.radius_m,
        ),
        "current_start": args.current_start,
        "current_end": args.current_end,
        "previous_start": args.previous_start,
        "previous_end": args.previous_end,
        "message": "已完成时间段对比分析。",
    }


def rank_roads_by_risk_tool(db: Session, args: RankRoadsByRiskArgs) -> dict[str, Any]:
    query, _ = _build_crack_query(
        db,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    rows = query.all()
    grouped: dict[str, list[models.CrackRecord]] = {}
    for row in rows:
        grouped.setdefault(row.road_name, []).append(row)

    ranked = []
    for road_name, road_rows in grouped.items():
        stats = _compute_stats_from_rows(road_rows)
        severe_penalty = stats["severe_count"] * 5.0
        density_bonus = min(len(road_rows) * 1.2, 12.0)
        grade_penalty = {"优": 0.0, "良": 4.0, "中": 10.0, "次": 18.0, "差": 28.0}.get(stats["technical_grade"], 0.0)
        risk_score = _round_risk_score(stats["avg_risk_score"] + severe_penalty + density_bonus + grade_penalty)
        ranked.append(
            {
                "road_name": road_name,
                "risk_score": risk_score,
                "total_count": stats["total_count"],
                "severe_count": stats["severe_count"],
                "medium_count": stats["medium_count"],
                "minor_count": stats["minor_count"],
                "total_length_m": stats["total_length_m"],
                "total_area_m2": stats["total_area_m2"],
                "avg_risk_score": stats["avg_risk_score"],
                "reference_pci": stats["reference_pci"],
                "reference_dr": stats["reference_dr"],
                "technical_grade": stats["technical_grade"],
                "maintenance_level": stats["maintenance_level"],
                "maintenance_label": stats["maintenance_label"],
            }
        )

    ranked.sort(key=lambda item: (-item["risk_score"], -item["severe_count"], item["road_name"]))
    return {
        "items": ranked[: args.limit],
        "count": min(len(ranked), args.limit),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "message": "已完成道路风险排序。",
    }


def find_high_risk_cracks_tool(db: Session, args: FindHighRiskCracksArgs) -> dict[str, Any]:
    query, resolved_road_name = _build_crack_query(
        db,
        road_name=args.road_name,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    rows = query.all()
    rows_with_distance = _filter_rows_by_radius(
        rows,
        center_latitude=args.center_latitude,
        center_longitude=args.center_longitude,
        radius_m=args.radius_m,
    )
    ranked_rows = sorted(rows_with_distance, key=lambda item: _compute_crack_risk_score(item[0]), reverse=True)[: args.limit]
    items = [serialize_crack(row, distance_m=distance) for row, distance in ranked_rows]
    return {
        "items": items,
        "count": len(items),
        "road_name": resolved_road_name,
        "spatial_filter": _spatial_context(
            center_latitude=args.center_latitude,
            center_longitude=args.center_longitude,
            radius_m=args.radius_m,
        ),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "message": "已返回高风险裂缝列表。",
    }


def analyze_surrounding_pois_tool(db: Session, args: AnalyzeSurroundingPoisArgs) -> dict[str, Any]:
    latitude = args.latitude
    longitude = args.longitude
    selected_rows: list[models.CrackRecord] = []

    if args.crack_ids:
        selected_rows = (
            db.query(models.CrackRecord)
            .filter(models.CrackRecord.id.in_(args.crack_ids))
            .order_by(models.CrackRecord.severity_level.desc(), models.CrackRecord.detected_at.desc())
            .limit(args.max_points)
            .all()
        )
        if selected_rows and (latitude is None or longitude is None):
            latitude = float(selected_rows[0].latitude)
            longitude = float(selected_rows[0].longitude)

    if latitude is None or longitude is None:
        raise ValueError("需要提供 crack_ids 或明确的经纬度。")

    if selected_rows:
        point_results = []
        total_exposure_score = 0.0
        merged_counts: Counter[str] = Counter()
        all_pois: list[dict[str, object]] = []
        enabled: bool | None = None
        source = "unknown"
        error_message: str | None = None
        for row in selected_rows:
            summary = summarize_sensitive_pois(float(row.latitude), float(row.longitude), radius_m=args.radius_m)
            enabled = summary.enabled if enabled is None else enabled and summary.enabled
            source = summary.source
            if summary.error_message:
                error_message = summary.error_message
            total_exposure_score += float(summary.exposure_score or 0.0)
            merged_counts.update(summary.counts or {})
            nearby_pois = [
                dict(poi)
                for poi in summary.pois
                if poi.get("distance") is not None and float(poi.get("distance") or 0.0) <= args.radius_m
            ]
            for poi in nearby_pois[:3]:
                all_pois.append(
                    {
                        **poi,
                        "crack_id": row.id,
                        "identity_id": row.identity_id,
                        "identity_code": row.identity.identity_code if row.identity else None,
                    }
                )
            point_results.append(
                {
                    "crack_id": row.id,
                    "identity_id": row.identity_id,
                    "identity_code": row.identity.identity_code if row.identity else None,
                    "road_name": row.road_name,
                    "severity_label": row.severity_label,
                    "latitude": float(row.latitude),
                    "longitude": float(row.longitude),
                    "enabled": summary.enabled,
                    "source": summary.source,
                    "radius_m": summary.radius_m,
                    "exposure_score": summary.exposure_score,
                    "counts": summary.counts,
                    "sensitive_poi_count": len(nearby_pois),
                    "nearest_sensitive_poi": nearby_pois[0] if nearby_pois else None,
                    "pois": nearby_pois,
                    "error_message": summary.error_message,
                }
            )
        return {
            "enabled": bool(enabled),
            "source": source,
            "radius_m": args.radius_m,
            "exposure_score": round(total_exposure_score / len(point_results), 1) if point_results else 0.0,
            "counts": dict(merged_counts),
            "pois": all_pois[: args.max_points],
            "points": point_results,
            "related_crack_ids": [row.id for row in selected_rows],
            "error_message": error_message,
            "message": "已完成裂缝逐点周边敏感设施分析。" if enabled else "未启用高德周边设施分析。",
        }

    summary = summarize_sensitive_pois(latitude, longitude, radius_m=args.radius_m)
    return {
        "enabled": summary.enabled,
        "source": summary.source,
        "radius_m": summary.radius_m,
        "exposure_score": summary.exposure_score,
        "counts": summary.counts,
        "pois": list(summary.pois),
        "related_crack_ids": [row.id for row in selected_rows],
        "error_message": summary.error_message,
        "message": "已完成周边敏感设施分析。" if summary.enabled else "未启用高德周边设施分析。",
    }


def build_map_geojson_tool(db: Session, args: CrackIdsArgs) -> dict[str, Any]:
    if not args.crack_ids:
        return {"type": "FeatureCollection", "features": []}

    rows = (
        db.query(models.CrackRecord)
        .options(
            joinedload(models.CrackRecord.identity),
            joinedload(models.CrackRecord.frame),
        )
        .filter(models.CrackRecord.id.in_(args.crack_ids))
        .order_by(models.CrackRecord.severity_level.desc(), models.CrackRecord.detected_at.desc())
        .all()
    )
    found_ids = {row.id for row in rows}
    missing_ids = [item for item in args.crack_ids if item not in found_ids]
    if missing_ids:
        identity_rows = (
            db.query(models.CrackIdentity)
            .filter(models.CrackIdentity.id.in_(missing_ids))
            .order_by(models.CrackIdentity.current_severity_level.desc(), models.CrackIdentity.last_seen_at.desc())
            .all()
        )
        for identity in identity_rows:
            latest_record = (
                db.query(models.CrackRecord)
                .filter(models.CrackRecord.identity_id == identity.id)
                .order_by(models.CrackRecord.detected_at.desc())
                .first()
            )
            if latest_record:
                rows.append(latest_record)
    unique_rows = []
    seen_row_ids = set()
    for row in rows:
        if row.id in seen_row_ids:
            continue
        seen_row_ids.add(row.id)
        unique_rows.append(row)
    rows = unique_rows
    features = []
    for row in rows:
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row.longitude), float(row.latitude)],
                },
                "properties": {
                    "id": row.id,
                    "identity_id": row.identity_id,
                    "identity_code": row.identity.identity_code if row.identity else None,
                    "crack_code": row.crack_code,
                    "task_id": row.task_id,
                    "frame_id": row.frame_id,
                    "frame_code": row.frame.frame_code if row.frame else None,
                    "road_name": row.road_name,
                    "district": row.district,
                    "severity": row.severity_level,
                    "severity_label": row.severity_label,
                    "risk_score": _compute_crack_risk_score(row),
                    "crack_type": row.crack_type,
                    "length_m": round(float(row.length_m), 2),
                    "width_mm": round(float(row.avg_width_cm) * 10, 1),
                    "max_width_mm": round(float(row.max_width_cm) * 10, 1),
                    "area_m2": round(float(row.area_m2), 4),
                    "longitude": float(row.longitude),
                    "latitude": float(row.latitude),
                    "image_url": row.result_image_uri or row.original_image_uri,
                    "original_image_uri": row.frame.original_image_uri if row.frame else row.original_image_uri,
                    "result_image_uri": row.result_image_uri,
                    "mask_image_uri": row.frame.mask_image_uri if row.frame else None,
                    "detected_at": _serialize_datetime(row.detected_at),
                    "frame_id": row.frame_id,
                    "lifecycle_status": row.identity.lifecycle_status if row.identity else None,
                    "maintenance_status": row.identity.maintenance_status if row.identity else None,
                    "priority_level": row.identity.priority_level if row.identity else None,
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def get_crack_images_tool(db: Session, args: CrackIdsArgs) -> dict[str, Any]:
    if not args.crack_ids:
        return {"images": []}

    rows = (
        db.query(models.CrackRecord)
        .filter(models.CrackRecord.id.in_(args.crack_ids))
        .order_by(models.CrackRecord.severity_level.desc(), models.CrackRecord.detected_at.desc())
        .limit(6)
        .all()
    )
    found_ids = {row.id for row in rows}
    missing_ids = [item for item in args.crack_ids if item not in found_ids]
    if missing_ids and len(rows) < 6:
        identity_rows = (
            db.query(models.CrackIdentity)
            .filter(models.CrackIdentity.id.in_(missing_ids))
            .order_by(models.CrackIdentity.current_severity_level.desc(), models.CrackIdentity.last_seen_at.desc())
            .all()
        )
        for identity in identity_rows:
            latest_record = (
                db.query(models.CrackRecord)
                .filter(models.CrackRecord.identity_id == identity.id)
                .order_by(models.CrackRecord.detected_at.desc())
                .first()
            )
            if latest_record:
                rows.append(latest_record)
            if len(rows) >= 6:
                break
    unique_rows = []
    seen_row_ids = set()
    for row in rows:
        if row.id in seen_row_ids:
            continue
        seen_row_ids.add(row.id)
        unique_rows.append(row)
    rows = unique_rows[:6]
    images = [
        {
            "crack_id": row.id,
            "identity_id": row.identity_id,
            "identity_code": row.identity.identity_code if row.identity else None,
            "road_name": row.road_name,
            "severity_label": row.severity_label,
            "risk_score": _compute_crack_risk_score(row),
            "image_url": row.result_image_uri or row.original_image_uri,
            "detected_at": _serialize_datetime(row.detected_at),
        }
        for row in rows
        if row.result_image_uri or row.original_image_uri
    ]
    return {"images": images}


def analyze_crack_images_tool(db: Session, args: AnalyzeCrackImagesArgs) -> dict[str, Any]:
    from app.agent.llm_client import build_vision_llm_client
    from app.agent.prompts import build_crack_image_analysis_prompt

    if not args.crack_ids:
        return {
            "enabled": False,
            "images_analyzed": [],
            "summary": "",
            "findings": [],
            "message": "未提供裂缝 ID，无法进行图片分析。",
        }

    rows = (
        db.query(models.CrackRecord)
        .filter(models.CrackRecord.id.in_(args.crack_ids))
        .order_by(models.CrackRecord.severity_level.desc(), models.CrackRecord.detected_at.desc())
        .all()
    )
    row_by_id = {row.id: row for row in rows}

    selected_rows: list[models.CrackRecord] = []
    for crack_id in args.crack_ids:
        row = row_by_id.get(crack_id)
        if row and row not in selected_rows:
            selected_rows.append(row)
        if len(selected_rows) >= args.max_images:
            break

    if not selected_rows:
        return {
            "enabled": False,
            "images_analyzed": [],
            "summary": "",
            "findings": [],
            "message": "未找到可用于图片分析的裂缝记录。",
        }

    multimodal_parts: list[dict[str, Any]] = []
    images_analyzed: list[dict[str, Any]] = []

    for row in selected_rows:
        image_uri = row.result_image_uri or row.original_image_uri
        image_path = _resolve_upload_path(image_uri)
        if not image_path:
            continue

        try:
            data_url = _file_to_data_url(image_path)
        except OSError:
            continue

        crack_payload = serialize_crack(row)
        multimodal_parts.append(
            {
                "type": "text",
                "text": (
                    "裂缝图片样本："
                    f"crack_id={crack_payload['id']}，"
                    f"road_name={crack_payload['road_name'] or '-'}，"
                    f"severity_label={crack_payload['severity_label'] or '-'}，"
                    f"length_m={crack_payload['length_m']}，"
                    f"width_mm={crack_payload['width_mm']}，"
                    f"area_m2={crack_payload['area_m2']}，"
                    f"detected_at={crack_payload['detected_at'] or '-'}。"
                ),
            }
        )
        multimodal_parts.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": data_url,
                },
            }
        )
        images_analyzed.append(
            {
                "crack_id": row.id,
                "identity_id": row.identity_id,
                "identity_code": row.identity.identity_code if row.identity else None,
                "road_name": row.road_name,
                "severity_label": row.severity_label,
                "image_url": image_uri,
                "detected_at": _serialize_datetime(row.detected_at),
            }
        )

    if not images_analyzed:
        return {
            "enabled": False,
            "images_analyzed": [],
            "summary": "",
            "findings": [],
            "message": "未找到本地可访问的裂缝图片，已跳过图片分析。",
        }

    llm_client = build_vision_llm_client()
    prompt = build_crack_image_analysis_prompt(
        cracks=[serialize_crack(row) for row in selected_rows[: len(images_analyzed)]]
    )
    response = llm_client.generate(
        messages=[
            {"role": "system", "content": "你是道路裂缝图像辅助判读助手，只能根据提供的图片和结构化字段输出结论。"},
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}, *multimodal_parts],
            },
        ],
        tools_schema=[],
        runtime={"stage": "crack_image_analysis"},
    )
    if response.tool_calls:
        raise RuntimeError("裂缝图片分析阶段不应调用工具。")

    findings_text = (response.content or "").strip()
    if not findings_text:
        raise RuntimeError("视觉模型未返回图片分析结果。")

    findings = [line.strip("- ").strip() for line in findings_text.splitlines() if line.strip()]
    return {
        "enabled": True,
        "images_analyzed": images_analyzed,
        "summary": findings[0] if findings else findings_text,
        "findings": findings[:8],
        "raw_text": findings_text,
        "message": f"已完成 {len(images_analyzed)} 张裂缝图片的视觉判读。",
    }


def generate_maintenance_advice_tool(_: Session, args: GenerateMaintenanceAdviceArgs) -> dict[str, Any]:
    stats = args.stats or {}
    top_cracks = args.top_cracks or []
    total_count = int(stats.get("total_count") or 0)
    severe_count = int(stats.get("severe_count") or stats.get("serious_count") or 0)
    medium_count = int(stats.get("medium_count") or 0)
    avg_risk_score = float(stats.get("avg_risk_score") or 0.0)
    reference_pci = float(stats.get("reference_pci") or 100.0)
    reference_dr = float(stats.get("reference_dr") or 0.0)
    technical_grade = str(stats.get("technical_grade") or _pci_to_technical_grade(reference_pci))
    road_distribution = stats.get("road_distribution") or []
    poi_context = stats.get("poi_context") or {}
    poi_exposure_score = float(poi_context.get("exposure_score") or 0.0)
    max_width_mm = float(stats.get("max_width_mm") or 0.0)

    if total_count == 0 and not top_cracks:
        return {
            "priority_level": "低",
            "risk_score": 0.0,
            "summary": "当前未查询到裂缝记录，建议先补充巡检数据后再评估维修优先级。",
            "actions": ["暂无维修工单建议，保持常规巡检即可。"],
            "reason_factors": ["无裂缝记录"],
            "technical_grade": "优",
            "maintenance_level": "四级",
            "maintenance_label": "观察监测",
            "reference_pci": 100.0,
            "reference_dr": 0.0,
            "standard_basis": "参考 JTG 5210-2018 的 PCI/DR 对应关系与技术状况等级阈值推导。",
            "decision_mode": "rule_based",
            "max_priority_level": "低",
            "action_candidates": ["暂无维修工单建议，保持常规巡检即可。"],
        }

    top_risk = max((float(item.get("risk_score") or 0.0) for item in top_cracks), default=0.0)
    grade_penalty = {"优": 0.0, "良": 6.0, "中": 14.0, "次": 24.0, "差": 34.0}.get(technical_grade, 0.0)
    severe_penalty = severe_count * 5.5
    medium_penalty = medium_count * 2.0
    density_penalty = min(total_count * 0.9, 10.0)
    maintenance_risk_score = _round_risk_score(
        avg_risk_score
        + grade_penalty
        + top_risk * 0.22
        + severe_penalty
        + medium_penalty
        + density_penalty
        + poi_exposure_score * 0.12
    )

    maintenance_level, maintenance_label = _maintenance_level_from_grade(
        technical_grade,
        has_severe=severe_count > 0,
        max_width_mm=max_width_mm,
    )

    if maintenance_level == "一级":
        priority_level = "高"
    elif maintenance_level == "二级":
        priority_level = "中"
    else:
        priority_level = "低"

    reason_factors: list[str] = []
    reason_factors.append(f"参考 PCI 约为 {reference_pci:.1f}，对应技术状况等级为“{technical_grade}”")
    if reference_dr > 0:
        reason_factors.append(f"参考路面破损率 DR 约为 {reference_dr:.2f}")
    if severe_count >= 2:
        reason_factors.append("严重裂缝数量较多，已接近功能性与结构性病害并存状态")
    elif severe_count == 1:
        reason_factors.append("存在至少 1 处严重裂缝")
    if max_width_mm >= 5.0:
        reason_factors.append("最大裂缝宽度较大，需优先安排修补")
    if total_count >= 8:
        reason_factors.append("裂缝数量密度较高")
    if poi_exposure_score >= 40:
        reason_factors.append("周边存在较多学校、医院或交通站点等敏感设施")
    if not reason_factors:
        reason_factors.append("当前以中低风险裂缝为主")

    action_candidates: list[str] = []
    for item in top_cracks[:3]:
        width_mm = float(item.get("max_width_mm") or item.get("width_mm") or 0.0)
        action_candidates.append(
            f"优先处理 {item.get('road_name', '目标道路')} 的{item.get('severity_label', '高风险')}裂缝，参考 PCI {float(item.get('reference_pci') or 0):.1f}，裂缝宽度约 {width_mm:.1f} mm。"
        )
    if road_distribution:
        lead = road_distribution[0]
        action_candidates.append(f"建议优先复查 {lead.get('road_name', '重点道路')}，该道路当前裂缝记录最多。")
    if poi_exposure_score >= 40:
        action_candidates.append("建议将靠近学校、医院或交通站点的裂缝点位纳入优先工单，减少次生安全风险。")
    if maintenance_level == "一级":
        action_candidates.append("建议立即组织处治，优先实施封缝、灌缝或局部结构修复，并尽快复核相邻病害。")
    elif maintenance_level == "二级":
        action_candidates.append("建议优先纳入近期养护计划，先处理重度裂缝与宽缝，再做成片复查。")
    elif maintenance_level == "三级":
        action_candidates.append("建议结合月度或季度养护计划实施修补，并持续跟踪裂缝扩展。")
    else:
        action_candidates.append("当前可先安排常规巡检复核和局部预防性养护，不必启动高优先级封控。")

    unique_actions: list[str] = []
    for action in action_candidates:
        if action not in unique_actions:
            unique_actions.append(action)

    if maintenance_level == "一级":
        summary = f"当前路面参考技术等级为“{technical_grade}”，已达到立即维修条件，建议优先处置高风险裂缝点位。"
    elif maintenance_level == "二级":
        summary = f"当前路面参考技术等级为“{technical_grade}”，建议优先维修并尽快纳入近期养护计划。"
    elif maintenance_level == "三级":
        summary = f"当前路面参考技术等级为“{technical_grade}”，建议按计划维修，优先修补发展较快的裂缝。"
    else:
        summary = f"当前路面参考技术等级为“{technical_grade}”，整体风险可控，建议继续观察监测并安排常规维护。"

    return {
        "priority_level": priority_level,
        "risk_score": maintenance_risk_score,
        "summary": summary,
        "actions": unique_actions[:4],
        "reason_factors": reason_factors,
        "technical_grade": technical_grade,
        "maintenance_level": maintenance_level,
        "maintenance_label": maintenance_label,
        "reference_pci": round(reference_pci, 1),
        "reference_dr": round(reference_dr, 2),
        "standard_basis": "参考 JTG 5210-2018 第4章技术状况等级阈值与第7.4.5条 PCI/DR 对应关系推导。",
        "decision_mode": "rule_based",
        "max_priority_level": priority_level,
        "action_candidates": unique_actions[:6],
    }
