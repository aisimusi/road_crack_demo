from __future__ import annotations

import bisect
import base64
import binascii
import hashlib
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.crack_config import load_crack_config
from app import models
from app.database import IMAGES_UPLOAD_DIR, MASKS_UPLOAD_DIR, RESULTS_UPLOAD_DIR, UPLOADS_DIR
from app.services.geolocation import apply_task_location_from_srt_paths, is_review_task_type
from app.services.srt_parser import SrtEntry, parse_srt_file

try:
    import cv2
except ImportError:  # pragma: no cover - opencv is installed in the crack conda env.
    cv2 = None

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent
CRACK_CONFIG = load_crack_config()
CRACKMAMBA_ROOT = CRACK_CONFIG.crackmamba.root
CRACKMAMBA_PYTHON = CRACK_CONFIG.crackmamba.python
CRACKMAMBA_SCRIPT = CRACK_CONFIG.crackmamba.script
CRACKMAMBA_CHECKPOINT = CRACK_CONFIG.crackmamba.checkpoint
CRACKMAMBA_DEVICE = CRACK_CONFIG.crackmamba.device
CLASSIFIER_ENABLED = CRACK_CONFIG.classifier.enabled
CLASSIFIER_PYTHON = CRACK_CONFIG.classifier.python
CLASSIFIER_SCRIPT = CRACK_CONFIG.classifier.script
CLASSIFIER_CHECKPOINT = CRACK_CONFIG.classifier.checkpoint
CLASSIFIER_DEVICE = CRACK_CONFIG.classifier.device
CLASSIFIER_BATCH_SIZE = CRACK_CONFIG.classifier.batch_size
CLASSIFIER_MIN_CONFIDENCE = CRACK_CONFIG.classifier.min_confidence
CLASSIFIER_EMBEDDING_ENABLED = CRACK_CONFIG.classifier.embedding_enabled
CLASSIFIER_EMBEDDING_MODEL_NAME = CRACK_CONFIG.classifier.embedding_model_name
CLASSIFIER_EMBEDDING_SIMILARITY_THRESHOLD = CRACK_CONFIG.classifier.embedding_similarity_threshold
CLASSIFIER_EMBEDDING_MARGIN_THRESHOLD = CRACK_CONFIG.classifier.embedding_margin_threshold
FRAME_SAMPLE_FPS = CRACK_CONFIG.detection.frame_sample_fps
CRACK_DEDUP_DISTANCE_M = CRACK_CONFIG.detection.dedup_distance_m
CRACK_DEDUP_TIME_SECONDS = CRACK_CONFIG.detection.dedup_time_seconds
CRACK_DEDUP_SHAPE_IOU_THRESHOLD = CRACK_CONFIG.detection.dedup_shape_iou_threshold
CRACK_DEDUP_SHAPE_DICE_THRESHOLD = CRACK_CONFIG.detection.dedup_shape_dice_threshold
CRACK_DEDUP_CENTER_DISTANCE_RATIO = CRACK_CONFIG.detection.dedup_center_distance_ratio
CRACK_DEDUP_ORIENTATION_DEGREES = CRACK_CONFIG.detection.dedup_orientation_degrees
MASK_MIN_AREA_PX = CRACK_CONFIG.detection.mask_min_area_px
MASK_NOISE_MIN_AREA_PX = CRACK_CONFIG.detection.mask_noise_min_area_px
MASK_CONNECT_GAP_PX = CRACK_CONFIG.detection.mask_connect_gap_px
MASK_CONNECT_LINE_WIDTH_PX = CRACK_CONFIG.detection.mask_connect_line_width_px
MASK_MIN_COMPONENT_AREA_PX = CRACK_CONFIG.detection.mask_min_component_area_px
MASK_MIN_COMPONENT_LENGTH_PX = CRACK_CONFIG.detection.mask_min_component_length_px
MASK_MIN_COMPONENT_ELONGATION = CRACK_CONFIG.detection.mask_min_component_elongation
IDENTITY_MATCH_DISTANCE_M = CRACK_CONFIG.detection.identity_match_distance_m
IDENTITY_SHAPE_DICE_THRESHOLD = CRACK_CONFIG.detection.identity_shape_dice_threshold
IDENTITY_AREA_RATIO_MIN = CRACK_CONFIG.detection.identity_area_ratio_min
IDENTITY_ORIENTATION_DEGREES = CRACK_CONFIG.detection.identity_orientation_degrees
IDENTITY_CANDIDATE_DISTANCE_M = CRACK_CONFIG.detection.identity_candidate_distance_m
IDENTITY_GEO_SCORE_DISTANCE_M = CRACK_CONFIG.detection.identity_geo_score_distance_m
CRACKMAMBA_BATCH_SIZE = CRACK_CONFIG.crackmamba.batch_size
DJI_SENSOR_WIDTH_MM = CRACK_CONFIG.dji_camera.sensor_width_mm
DJI_SENSOR_HEIGHT_MM = CRACK_CONFIG.dji_camera.sensor_height_mm
FOCAL_LENGTH_IS_35MM_EQUIVALENT = CRACK_CONFIG.dji_camera.focal_length_is_35mm_equivalent
PHYSICAL_FOCAL_MIN_MM = CRACK_CONFIG.dji_camera.physical_focal_min_mm
EQUIVALENT_FOCAL_MIN_MM = CRACK_CONFIG.dji_camera.equivalent_focal_min_mm
CRACKMAMBA_CHECKPOINTS = {
    "crack9k": CRACKMAMBA_CHECKPOINT,
    "uav-crack": CRACKMAMBA_ROOT
    / "nnUNet_results"
    / "Dataset228_UAVImageCrack"
    / "nnUNetTrainerCrackMamba_500epochs__nnUNetPlans__2d"
    / "fold_all"
    / "checkpoint_best.pth",
    "earthquake": CRACKMAMBA_ROOT
    / "nnUNet_results"
    / "Dataset229_EarthquakeCrack"
    / "nnUNetTrainerCrackMamba_500epochs__nnUNetPlans__2d"
    / "fold_all"
    / "checkpoint_best.pth",
}

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}
SRT_EXTENSIONS = {".srt"}
QUADRANTS = (
    ("tl", (0, 0)),
    ("tr", (1, 0)),
    ("bl", (0, 1)),
    ("br", (1, 1)),
)
NEAREST_RESAMPLE = getattr(getattr(Image, "Resampling", Image), "NEAREST")
MASK_SHAPE_SIGNATURE_SIZE = 64


@dataclass(frozen=True)
class ProjectionCalibration:
    focal_scale: float = 1.0
    dzoom_power: float = 1.0
    pitch_offset_deg: float = 0.0
    altitude_scale: float = 1.0
    altitude_offset_m: float = 0.0
    min_altitude_m: float = 1.0


def _calibration_float(params: dict, key: str, default: float) -> float:
    try:
        return float(params.get(key, default))
    except (TypeError, ValueError):
        return default


def _load_projection_calibration(path: Path) -> ProjectionCalibration:
    if not path.exists():
        return ProjectionCalibration()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ProjectionCalibration()
    params = payload.get("parameters") if isinstance(payload, dict) else None
    if not isinstance(params, dict):
        params = payload if isinstance(payload, dict) else {}
    return ProjectionCalibration(
        focal_scale=max(_calibration_float(params, "focal_scale", 1.0), 0.001),
        dzoom_power=_calibration_float(params, "dzoom_power", 1.0),
        pitch_offset_deg=_calibration_float(params, "pitch_offset_deg", 0.0),
        altitude_scale=max(_calibration_float(params, "altitude_scale", 1.0), 0.001),
        altitude_offset_m=_calibration_float(params, "altitude_offset_m", 0.0),
        min_altitude_m=max(_calibration_float(params, "min_altitude_m", 1.0), 0.001),
    )


LANE_PROJECTION_CALIBRATION_PATH = PROJECT_ROOT / "calibration" / "lane_projection_calibration.json"
LANE_PROJECTION_CALIBRATION = _load_projection_calibration(LANE_PROJECTION_CALIBRATION_PATH)


@dataclass(frozen=True)
class FrameMeta:
    frame_path: Path
    stem: str
    elapsed_seconds: float
    srt: SrtEntry


@dataclass(frozen=True)
class VideoPair:
    video: models.MediaAsset
    srt: models.MediaAsset


@dataclass(frozen=True)
class MaskSignature:
    bbox: dict[str, int]
    area_px: int
    centroid_x: float
    centroid_y: float
    orientation_deg: float
    aspect_ratio: float
    shape_bitmap: np.ndarray


@dataclass(frozen=True)
class DetectionRecord:
    record_id: int
    frame: FrameMeta
    frame_path: Path
    mask_path: Path
    overlay_path: Path
    metrics: dict
    mask_signature: MaskSignature
    longitude: float
    latitude: float
    detected_at: datetime


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
        remark="由 CrackMamba 视频检测自动补充",
    )
    db.add(segment)
    db.flush()
    return segment


def guess_mime_type(path: Path, default: str = "application/octet-stream") -> str:
    mime_type, _ = mimetypes.guess_type(path.name)
    return mime_type or default


def resolve_file_uri_to_path(file_uri: str) -> Path:
    if file_uri.startswith("/uploads/"):
        return BACKEND_ROOT / file_uri.lstrip("/")
    path = Path(file_uri)
    if path.is_absolute():
        return path
    return BACKEND_ROOT / file_uri.lstrip("/")


def _delete_media_files(media_assets: list[models.MediaAsset]) -> None:
    for media in media_assets:
        file_path = resolve_file_uri_to_path(media.file_uri)
        if file_path.exists() and file_path.is_file():
            file_path.unlink(missing_ok=True)


def _clear_maintenance_record_links(db: Session, crack_record_ids: list[int]) -> None:
    if not crack_record_ids:
        return

    db.query(models.MaintenanceRecord).filter(
        models.MaintenanceRecord.before_record_id.in_(crack_record_ids)
    ).update(
        {models.MaintenanceRecord.before_record_id: None},
        synchronize_session=False,
    )
    db.query(models.MaintenanceRecord).filter(
        models.MaintenanceRecord.after_record_id.in_(crack_record_ids)
    ).update(
        {models.MaintenanceRecord.after_record_id: None},
        synchronize_session=False,
    )


def _maintenance_sort_key(record: models.MaintenanceRecord) -> datetime:
    return record.completed_at or record.updated_at or record.created_at or datetime.min


def _derive_identity_status(
    identity: models.CrackIdentity,
    records: list[models.CrackRecord],
    maintenance_records: list[models.MaintenanceRecord],
) -> tuple[str, str]:
    if identity.lifecycle_status == "archived":
        return "archived", identity.maintenance_status

    maintenance_status = "unrepaired"
    lifecycle_status = "active"
    if not maintenance_records:
        return lifecycle_status, maintenance_status

    latest_maintenance = max(maintenance_records, key=_maintenance_sort_key)
    raw_status = (latest_maintenance.status or "").strip()
    if raw_status in {"completed", "repaired"}:
        maintenance_status = "completed"
    elif raw_status in {"in_progress", "working"}:
        maintenance_status = "in_progress"
    elif raw_status:
        maintenance_status = raw_status

    if any((row.review_result or "").strip().lower() == "recurred" for row in maintenance_records):
        return "recurred", maintenance_status

    latest_completed_at = max(
        (
            row.completed_at or row.updated_at or row.created_at
            for row in maintenance_records
            if (row.status or "").strip() in {"completed", "repaired"}
        ),
        default=None,
    )
    if latest_completed_at is None:
        return lifecycle_status, maintenance_status

    has_post_repair_observation = any(
        (record.detected_at or datetime.min) > latest_completed_at for record in records
    )
    lifecycle_status = "recurred" if has_post_repair_observation else "repaired"
    return lifecycle_status, maintenance_status


def _rebuild_crack_identity_snapshot(db: Session, identity: models.CrackIdentity) -> None:
    records = (
        db.query(models.CrackRecord)
        .filter(models.CrackRecord.identity_id == identity.id)
        .order_by(models.CrackRecord.detected_at.asc(), models.CrackRecord.id.asc())
        .all()
    )
    if not records:
        db.delete(identity)
        return

    maintenance_records = (
        db.query(models.MaintenanceRecord)
        .filter(models.MaintenanceRecord.identity_id == identity.id)
        .all()
    )

    latest_record = records[-1]
    previous_record = records[-2] if len(records) > 1 else None
    growth_area_m2 = 0.0
    growth_length_m = 0.0
    if previous_record is not None:
        growth_area_m2 = round(float(latest_record.area_m2 or 0.0) - float(previous_record.area_m2 or 0.0), 4)
        growth_length_m = round(float(latest_record.length_m or 0.0) - float(previous_record.length_m or 0.0), 3)

    preserve_signature = (
        identity.last_task_id == latest_record.task_id
        and identity.latest_original_image_uri == latest_record.original_image_uri
        and identity.latest_result_image_uri == latest_record.result_image_uri
    )
    lifecycle_status, maintenance_status = _derive_identity_status(identity, records, maintenance_records)
    longitudes = [float(item.longitude) for item in records]
    latitudes = [float(item.latitude) for item in records]

    identity.road_segment_id = latest_record.road_segment_id
    identity.road_name = latest_record.road_name
    identity.district = latest_record.district
    identity.crack_type = latest_record.crack_type
    identity.lifecycle_status = lifecycle_status
    identity.maintenance_status = maintenance_status
    identity.observation_count = len(records)
    identity.first_seen_at = records[0].detected_at
    identity.last_seen_at = latest_record.detected_at
    identity.last_task_id = latest_record.task_id
    identity.center_longitude = sum(longitudes) / len(longitudes)
    identity.center_latitude = sum(latitudes) / len(latitudes)
    identity.latest_longitude = latest_record.longitude
    identity.latest_latitude = latest_record.latitude
    identity.current_severity_level = latest_record.severity_level
    identity.current_severity_label = latest_record.severity_label
    identity.current_severity_score = float(latest_record.severity_score or 0.0)
    identity.current_length_m = float(latest_record.length_m or 0.0)
    identity.current_avg_width_cm = float(latest_record.avg_width_cm or 0.0)
    identity.current_max_width_cm = float(latest_record.max_width_cm or 0.0)
    identity.current_area_m2 = float(latest_record.area_m2 or 0.0)
    identity.max_severity_level = max(int(item.severity_level or 0) for item in records)
    identity.max_area_m2 = max(float(item.area_m2 or 0.0) for item in records)
    identity.growth_area_m2 = growth_area_m2
    identity.growth_length_m = growth_length_m
    identity.priority_level = _priority_from_severity(latest_record.severity_level, growth_area_m2)
    identity.latest_original_image_uri = latest_record.original_image_uri
    identity.latest_result_image_uri = latest_record.result_image_uri
    latest_record_embedding = _embedding_from_json(latest_record.embedding_json)
    if latest_record_embedding:
        identity.embedding_json = _embedding_to_json(latest_record_embedding)
        identity.embedding_model = latest_record.embedding_model or CLASSIFIER_EMBEDDING_MODEL_NAME
        identity.embedding_count = sum(1 for item in records if item.embedding_json)

    if not preserve_signature:
        identity.feature_hash = None
        identity.feature_json = None
        if not latest_record_embedding:
            identity.embedding_json = None
            identity.embedding_model = None
            identity.embedding_count = 0
        if identity.remark and identity.remark.startswith("最近匹配:"):
            identity.remark = None


def _refresh_identities_after_record_change(db: Session, identity_ids: list[int]) -> None:
    for identity_id in sorted(set(identity_ids)):
        identity = db.get(models.CrackIdentity, identity_id)
        if identity is None:
            continue
        _rebuild_crack_identity_snapshot(db, identity)


def delete_task_crack_data(db: Session, task_id: int) -> None:
    task_rows = (
        db.query(models.CrackRecord.id, models.CrackRecord.identity_id)
        .filter(models.CrackRecord.task_id == task_id)
        .all()
    )
    crack_record_ids = [int(row.id) for row in task_rows]
    identity_ids = [int(row.identity_id) for row in task_rows if row.identity_id is not None]

    _clear_maintenance_record_links(db, crack_record_ids)
    db.query(models.MaintenanceRecord).filter(models.MaintenanceRecord.task_id == task_id).delete(
        synchronize_session=False
    )
    db.query(models.CrackRecord).filter(models.CrackRecord.task_id == task_id).delete(synchronize_session=False)
    db.query(models.InspectionFrame).filter(models.InspectionFrame.task_id == task_id).delete(synchronize_session=False)
    _refresh_identities_after_record_change(db, identity_ids)
    db.flush()


def purge_existing_task_results(db: Session, task_id: int) -> None:
    task_rows = (
        db.query(models.CrackRecord.id, models.CrackRecord.identity_id)
        .filter(models.CrackRecord.task_id == task_id)
        .all()
    )
    crack_record_ids = [int(row.id) for row in task_rows]
    existing_identity_ids = [int(row.identity_id) for row in task_rows if row.identity_id is not None]
    existing_media = (
        db.query(models.MediaAsset)
        .filter(models.MediaAsset.task_id == task_id, models.MediaAsset.category != "uploaded")
        .all()
    )
    _delete_media_files(existing_media)

    _clear_maintenance_record_links(db, crack_record_ids)
    db.query(models.CrackRecord).filter(models.CrackRecord.task_id == task_id).delete(synchronize_session=False)
    db.query(models.InspectionFrame).filter(models.InspectionFrame.task_id == task_id).delete(synchronize_session=False)
    db.query(models.MediaAsset).filter(
        models.MediaAsset.task_id == task_id,
        models.MediaAsset.category != "uploaded",
    ).delete(synchronize_session=False)
    _refresh_identities_after_record_change(db, existing_identity_ids)
    db.flush()


def _match_srt_entry(entries: list[SrtEntry], elapsed_seconds: float) -> SrtEntry:
    starts = [entry.start_seconds for entry in entries]
    position = bisect.bisect_left(starts, elapsed_seconds)
    candidates = []
    if position < len(entries):
        candidates.append(entries[position])
    if position > 0:
        candidates.append(entries[position - 1])
    if not candidates:
        return entries[0]
    return min(
        candidates,
        key=lambda entry: min(
            abs(entry.start_seconds - elapsed_seconds),
            abs(entry.end_seconds - elapsed_seconds),
        ),
    )


def _safe_stem(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "video"


def _run_ffmpeg_extract_frames(video_path: Path, frames_dir: Path) -> None:
    frames_dir.mkdir(parents=True, exist_ok=True)
    pattern = frames_dir / "frame_%06d.png"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"fps={FRAME_SAMPLE_FPS:g}",
            str(pattern),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _set_task_progress(db: Session, task_id: int, percent: int, message: str) -> None:
    task = db.get(models.InspectionTask, task_id)
    if not task:
        return
    task.progress_percent = max(0, min(100, int(percent)))
    task.progress_message = message
    db.commit()


def _extract_frame_seconds(frame_path: Path) -> float:
    match = re.search(r"frame_(\d+)", frame_path.stem)
    if not match:
        return 0.0
    frame_index = int(match.group(1))
    return (frame_index - 1) / FRAME_SAMPLE_FPS


def _prepare_video_frames(video_path: Path, srt_entries: list[SrtEntry], frames_dir: Path) -> list[FrameMeta]:
    _run_ffmpeg_extract_frames(video_path, frames_dir)
    frame_paths = sorted(frames_dir.glob("frame_*.png"))
    if not frame_paths:
        raise FileNotFoundError(f"视频未抽取到任何帧: {video_path.name}")

    video_stem = _safe_stem(video_path.stem)
    frames: list[FrameMeta] = []
    for frame_path in frame_paths:
        elapsed_seconds = _extract_frame_seconds(frame_path)
        stem = f"{video_stem}_{frame_path.stem}"
        normalized_frame = frame_path.with_name(f"{stem}.png")
        if normalized_frame != frame_path:
            frame_path.rename(normalized_frame)
            frame_path = normalized_frame
        frames.append(
            FrameMeta(
                frame_path=frame_path,
                stem=stem,
                elapsed_seconds=elapsed_seconds,
                srt=_match_srt_entry(srt_entries, elapsed_seconds),
            )
        )
    return frames


def _split_frames_into_tiles(frames: list[FrameMeta], tiles_dir: Path) -> None:
    tiles_dir.mkdir(parents=True, exist_ok=True)
    for frame in frames:
        with Image.open(frame.frame_path) as image:
            rgb_image = image.convert("RGB")
            width, height = rgb_image.size
            half_w = width // 2
            half_h = height // 2
            boxes = {
                "tl": (0, 0, half_w, half_h),
                "tr": (half_w, 0, width, half_h),
                "bl": (0, half_h, half_w, height),
                "br": (half_w, half_h, width, height),
            }
            for quadrant, box in boxes.items():
                tile_path = tiles_dir / f"{frame.stem}_{quadrant}.png"
                rgb_image.crop(box).save(tile_path)


def resolve_checkpoint(weight_name: str) -> Path:
    checkpoint = CRACKMAMBA_CHECKPOINTS.get(weight_name)
    if checkpoint is None:
        allowed = ", ".join(CRACKMAMBA_CHECKPOINTS)
        raise ValueError(f"未知检测权重: {weight_name}，可选值: {allowed}")
    return checkpoint


def _run_crackmamba_batch(input_dir: Path, output_dir: Path, checkpoint: Path) -> list[dict]:
    missing = [
        path for path in (CRACKMAMBA_PYTHON, CRACKMAMBA_SCRIPT, checkpoint)
        if not path.exists()
    ]
    if missing:
        missing_text = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(f"CrackMamba 运行依赖缺失: {missing_text}")

    env = os.environ.copy()
    env.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-roadcrack")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{CRACKMAMBA_ROOT}:{existing_pythonpath}" if existing_pythonpath else str(CRACKMAMBA_ROOT)
    cmd = [
        str(CRACKMAMBA_PYTHON),
        str(CRACKMAMBA_SCRIPT),
        "--input-dir",
        str(input_dir),
        "--output-dir",
        str(output_dir),
        "--checkpoint",
        str(checkpoint),
        "--device",
        CRACKMAMBA_DEVICE,
    ]
    if CRACKMAMBA_BATCH_SIZE > 1:
        cmd.extend(["--batch-size", str(CRACKMAMBA_BATCH_SIZE)])
    subprocess.run(cmd, check=True, cwd=str(CRACKMAMBA_ROOT), env=env)
    results_path = output_dir / "results.json"
    return json.loads(results_path.read_text(encoding="utf-8"))


def _heuristic_crack_type(mask: np.ndarray, srt: SrtEntry) -> str:
    ground_metrics = _ground_bbox_metrics(mask, _mask_bbox(mask), srt)
    return "longitudinal_crack" if ground_metrics["bbox_height_m"] >= ground_metrics["bbox_width_m"] else "transverse_crack"


def _crop_bounds_from_bbox(
    bbox: dict[str, int],
    image_width: int,
    image_height: int,
    *,
    padding_ratio: float = 0.3,
) -> tuple[int, int, int, int]:
    bbox_x = max(0, int(bbox.get("x", 0)))
    bbox_y = max(0, int(bbox.get("y", 0)))
    bbox_width = max(1, int(bbox.get("width", 1)))
    bbox_height = max(1, int(bbox.get("height", 1)))
    padding_x = max(24, int(bbox_width * padding_ratio))
    padding_y = max(24, int(bbox_height * padding_ratio))
    left = max(0, bbox_x - padding_x)
    top = max(0, bbox_y - padding_y)
    right = min(image_width, bbox_x + bbox_width + padding_x)
    bottom = min(image_height, bbox_y + bbox_height + padding_y)
    if right <= left:
        right = min(image_width, left + bbox_width)
    if bottom <= top:
        bottom = min(image_height, top + bbox_height)
    return left, top, right, bottom


def _save_classifier_crop(
    frame_path: Path,
    mask: np.ndarray,
    bbox: dict[str, int],
    crop_path: Path,
) -> None:
    with Image.open(frame_path) as image:
        rgb = image.convert("RGB")
        left, top, right, bottom = _crop_bounds_from_bbox(bbox, rgb.width, rgb.height)
        crop = rgb.crop((left, top, right, bottom))
        mask_crop = mask[top:bottom, left:right]
        if mask_crop.shape[:2] == (bottom - top, right - left) and mask_crop.any():
            crop_array = np.array(crop, dtype=np.uint8)
            bright_bg = np.full_like(crop_array, 245)
            softened_bg = ((crop_array.astype(np.float32) * 0.75) + (bright_bg.astype(np.float32) * 0.25)).astype(
                np.uint8
            )
            crop_array = np.where(mask_crop[..., None], crop_array, softened_bg)
            crop = Image.fromarray(crop_array, mode="RGB")
        crop.save(crop_path, format="JPEG", quality=95)


def _run_crack_classifier(crop_items: list[dict[str, object]], work_root: Path) -> dict[int, dict[str, object]]:
    if not CLASSIFIER_ENABLED:
        return {}

    missing = [
        path for path in (CLASSIFIER_PYTHON, CLASSIFIER_SCRIPT)
        if not path.exists()
    ]
    if missing:
        return {}

    classifier_input_path = work_root / "classifier_input.json"
    classifier_output_path = work_root / "classifier_output.json"
    classifier_input_path.write_text(json.dumps(crop_items, ensure_ascii=False, indent=2), encoding="utf-8")

    cmd = [
        str(CLASSIFIER_PYTHON),
        str(CLASSIFIER_SCRIPT),
        "--input-json",
        str(classifier_input_path),
        "--output-json",
        str(classifier_output_path),
        "--checkpoint",
        str(CLASSIFIER_CHECKPOINT),
        "--device",
        CLASSIFIER_DEVICE,
        "--batch-size",
        str(CLASSIFIER_BATCH_SIZE),
        "--min-confidence",
        str(CLASSIFIER_MIN_CONFIDENCE),
    ]
    if CLASSIFIER_EMBEDDING_ENABLED:
        cmd.append("--emit-embeddings")
    env = os.environ.copy()
    env.setdefault("MPLCONFIGDIR", "/tmp/matplotlib-roadcrack")
    subprocess.run(cmd, check=True, cwd=str(PROJECT_ROOT), env=env)
    if not classifier_output_path.exists():
        return {}

    payload = json.loads(classifier_output_path.read_text(encoding="utf-8"))
    predictions_by_id: dict[int, dict[str, object]] = {}
    for item in payload.get("predictions", []):
        record_id = int(item.get("record_id") or 0)
        if record_id > 0:
            predictions_by_id[record_id] = item
    return predictions_by_id


def _safe_float_list(value: object) -> list[float] | None:
    if not isinstance(value, list) or not value:
        return None
    result: list[float] = []
    for item in value:
        try:
            result.append(float(item))
        except (TypeError, ValueError):
            return None
    return result


def _normalize_embedding_vector(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 1e-12:
        return values
    return [value / norm for value in values]


def _embedding_from_json(payload: str | None) -> list[float] | None:
    if not payload:
        return None
    try:
        parsed = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return _safe_float_list(parsed)


def _embedding_to_json(values: list[float] | None) -> str | None:
    if not values:
        return None
    rounded = [round(float(value), 6) for value in values]
    return json.dumps(rounded, ensure_ascii=False, separators=(",", ":"))


def _cosine_similarity(a: list[float] | None, b: list[float] | None) -> float | None:
    if not a or not b or len(a) != len(b):
        return None
    return float(sum(x * y for x, y in zip(a, b)))


def _tile_name_parts(tile_image_name: str) -> tuple[str, str] | None:
    stem = Path(tile_image_name).stem
    match = re.match(r"(.+)_(tl|tr|bl|br)$", stem)
    if not match:
        return None
    return match.group(1), match.group(2)


def _load_tile_masks(batch_results: list[dict], output_dir: Path) -> dict[str, dict[str, np.ndarray]]:
    grouped: dict[str, dict[str, np.ndarray]] = {}
    for item in batch_results:
        parts = _tile_name_parts(item.get("image_name", ""))
        if not parts:
            continue
        frame_stem, quadrant = parts
        result_image = output_dir / item["result_image"]
        if not result_image.exists():
            continue
        with Image.open(result_image) as image:
            mask = np.array(image.convert("L")) > 0
        grouped.setdefault(frame_stem, {})[quadrant] = mask
    return grouped


def _stitch_full_mask(frame_path: Path, tile_masks: dict[str, np.ndarray]) -> np.ndarray:
    with Image.open(frame_path) as image:
        width, height = image.size
    half_w = width // 2
    half_h = height // 2
    full_mask = np.zeros((height, width), dtype=bool)
    boxes = {
        "tl": (slice(0, half_h), slice(0, half_w)),
        "tr": (slice(0, half_h), slice(half_w, width)),
        "bl": (slice(half_h, height), slice(0, half_w)),
        "br": (slice(half_h, height), slice(half_w, width)),
    }
    for quadrant, (ys, xs) in boxes.items():
        mask = tile_masks.get(quadrant)
        if mask is None:
            continue
        target_h = ys.stop - ys.start
        target_w = xs.stop - xs.start
        if mask.shape != (target_h, target_w):
            mask_image = Image.fromarray((mask.astype(np.uint8) * 255), mode="L").resize(
                (target_w, target_h),
                NEAREST_RESAMPLE,
            )
            mask = np.array(mask_image) > 0
        full_mask[ys, xs] = mask
    return full_mask


def _component_elongation(width: int, height: int) -> float:
    return max(width, height) / max(min(width, height), 1)


def _connected_components(mask: np.ndarray) -> list[dict[str, object]]:
    if not mask.any():
        return []

    components: list[dict[str, object]] = []
    if cv2 is not None:
        labels_count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
        for label in range(1, labels_count):
            area_px = int(stats[label, cv2.CC_STAT_AREA])
            if area_px <= 0:
                continue
            x = int(stats[label, cv2.CC_STAT_LEFT])
            y = int(stats[label, cv2.CC_STAT_TOP])
            width = int(stats[label, cv2.CC_STAT_WIDTH])
            height = int(stats[label, cv2.CC_STAT_HEIGHT])
            components.append(
                {
                    "area": area_px,
                    "bbox": {"x": x, "y": y, "width": width, "height": height},
                    "mask": labels == label,
                }
            )
        return components

    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    ys, xs = np.where(mask)
    for start_y, start_x in zip(ys.tolist(), xs.tolist()):
        if visited[start_y, start_x]:
            continue
        component_mask = np.zeros_like(mask, dtype=bool)
        stack = [(start_y, start_x)]
        visited[start_y, start_x] = True
        comp_ys: list[int] = []
        comp_xs: list[int] = []
        while stack:
            y, x = stack.pop()
            component_mask[y, x] = True
            comp_ys.append(y)
            comp_xs.append(x)
            for ny in range(max(0, y - 1), min(height, y + 2)):
                for nx in range(max(0, x - 1), min(width, x + 2)):
                    if visited[ny, nx] or not mask[ny, nx]:
                        continue
                    visited[ny, nx] = True
                    stack.append((ny, nx))
        x1, x2 = min(comp_xs), max(comp_xs)
        y1, y2 = min(comp_ys), max(comp_ys)
        components.append(
            {
                "area": len(comp_xs),
                "bbox": {"x": x1, "y": y1, "width": x2 - x1 + 1, "height": y2 - y1 + 1},
                "mask": component_mask,
            }
        )
    return components


def _directional_kernel(length: int, line_width: int, angle_deg: float) -> np.ndarray:
    length = max(1, int(length))
    line_width = max(1, int(line_width))
    side = max(length, line_width)
    if side % 2 == 0:
        side += 1
    kernel = np.zeros((side, side), dtype=np.uint8)
    center = side // 2
    radius = length // 2
    angle_rad = math.radians(angle_deg)
    dx = math.cos(angle_rad) * radius
    dy = math.sin(angle_rad) * radius
    x1 = int(round(center - dx))
    y1 = int(round(center - dy))
    x2 = int(round(center + dx))
    y2 = int(round(center + dy))
    if cv2 is not None:
        cv2.line(kernel, (x1, y1), (x2, y2), 1, thickness=line_width)
        return kernel

    steps = max(abs(x2 - x1), abs(y2 - y1), 1)
    for step in range(steps + 1):
        t = step / steps
        x = int(round(x1 + (x2 - x1) * t))
        y = int(round(y1 + (y2 - y1) * t))
        y_start = max(0, y - line_width // 2)
        y_end = min(side, y + line_width // 2 + 1)
        x_start = max(0, x - line_width // 2)
        x_end = min(side, x + line_width // 2 + 1)
        kernel[y_start:y_end, x_start:x_end] = 1
    return kernel


def _binary_dilate_numpy(mask: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    kernel = kernel.astype(bool)
    if not kernel.any() or not mask.any():
        return mask.copy()
    pad_y = kernel.shape[0] // 2
    pad_x = kernel.shape[1] // 2
    padded = np.pad(mask, ((pad_y, pad_y), (pad_x, pad_x)), mode="constant", constant_values=False)
    dilated = np.zeros_like(mask, dtype=bool)
    ky, kx = np.where(kernel)
    for y_offset, x_offset in zip(ky.tolist(), kx.tolist()):
        dilated |= padded[y_offset : y_offset + mask.shape[0], x_offset : x_offset + mask.shape[1]]
    return dilated


def _binary_dilate(mask: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    if cv2 is not None:
        return cv2.dilate(mask.astype(np.uint8), kernel.astype(np.uint8), iterations=1).astype(bool)
    return _binary_dilate_numpy(mask, kernel)


def _remove_tiny_noise_components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    if MASK_NOISE_MIN_AREA_PX <= 0 or not mask.any():
        return mask.astype(bool), 0

    cleaned = np.zeros_like(mask, dtype=bool)
    removed_count = 0
    for component in _connected_components(mask):
        area_px = int(component["area"])
        if area_px < MASK_NOISE_MIN_AREA_PX:
            removed_count += 1
            continue
        cleaned |= component["mask"]  # type: ignore[operator]
    return cleaned, removed_count


def _bridge_crack_mask(mask: np.ndarray) -> np.ndarray:
    if MASK_CONNECT_GAP_PX <= 0 or not mask.any():
        return mask.astype(bool)

    bridged = mask.astype(bool)
    kernel_length = max(3, MASK_CONNECT_GAP_PX + 1)
    for angle in (0.0, 45.0, 90.0, 135.0):
        kernel = _directional_kernel(kernel_length, MASK_CONNECT_LINE_WIDTH_PX, angle)
        bridged |= _binary_dilate(mask, kernel)
    return bridged


def _should_keep_mask_component(area_px: int, width: int, height: int) -> bool:
    if area_px < MASK_MIN_COMPONENT_AREA_PX:
        return False
    if max(width, height) < MASK_MIN_COMPONENT_LENGTH_PX:
        return False
    if _component_elongation(width, height) >= MASK_MIN_COMPONENT_ELONGATION:
        return True
    return area_px >= max(MASK_MIN_AREA_PX, MASK_MIN_COMPONENT_AREA_PX * 4)


def _collect_crack_instance_masks(mask: np.ndarray) -> tuple[list[np.ndarray], dict[str, int]]:
    if not mask.any():
        return [], {
            "components_before": 0,
            "components_after": 0,
            "noise_components_removed": 0,
            "bridge_gap_px": MASK_CONNECT_GAP_PX,
            "mask_area_px": 0,
        }

    denoised, removed_count = _remove_tiny_noise_components(mask)
    if not denoised.any():
        return [], {
            "components_before": 0,
            "components_after": 0,
            "noise_components_removed": removed_count,
            "bridge_gap_px": MASK_CONNECT_GAP_PX,
            "mask_area_px": 0,
        }

    before_components = _connected_components(denoised)
    bridge_mask = _bridge_crack_mask(denoised)
    bridge_components = _connected_components(bridge_mask)
    instances: list[tuple[int, np.ndarray]] = []

    for bridge_component in bridge_components:
        component_bridge_mask = bridge_component["mask"]  # type: ignore[assignment]
        instance_mask = np.logical_and(denoised, component_bridge_mask)
        area_px = int(instance_mask.sum())
        if area_px <= 0:
            continue
        bbox = _mask_bbox(instance_mask)
        if not _should_keep_mask_component(area_px, bbox["width"], bbox["height"]):
            continue
        instances.append((area_px, instance_mask))

    instances.sort(key=lambda item: item[0], reverse=True)
    instance_masks = [instance for _, instance in instances]
    cleaned_area_px = int(sum(int(instance.sum()) for instance in instance_masks))
    if cleaned_area_px < MASK_MIN_AREA_PX:
        instance_masks = []
        cleaned_area_px = 0

    return instance_masks, {
        "components_before": len(before_components),
        "components_after": len(instance_masks),
        "noise_components_removed": removed_count,
        "bridge_components": len(bridge_components),
        "bridge_gap_px": MASK_CONNECT_GAP_PX,
        "mask_area_px": cleaned_area_px,
    }


def _filter_mask_components_cv2(mask: np.ndarray) -> tuple[np.ndarray, dict[str, int]]:
    instances, stats = _collect_crack_instance_masks(mask)
    if not instances:
        return np.zeros_like(mask, dtype=bool), stats
    return np.logical_or.reduce(instances), stats


def _filter_mask_components_numpy(mask: np.ndarray) -> tuple[np.ndarray, dict[str, int]]:
    instances, stats = _collect_crack_instance_masks(mask)
    if not instances:
        return np.zeros_like(mask, dtype=bool), stats
    return np.logical_or.reduce(instances), stats


def _filter_crack_mask(mask: np.ndarray) -> tuple[np.ndarray, dict[str, int]]:
    if not mask.any():
        return mask, {"components_before": 0, "components_after": 0, "mask_area_px": 0}

    if cv2 is not None:
        cleaned, stats = _filter_mask_components_cv2(mask)
    else:
        cleaned, stats = _filter_mask_components_numpy(mask)

    mask_area_px = int(cleaned.sum())
    stats["mask_area_px"] = mask_area_px
    if mask_area_px < MASK_MIN_AREA_PX:
        return np.zeros_like(mask, dtype=bool), stats
    return cleaned, stats


def _split_crack_instance_masks(mask: np.ndarray) -> list[np.ndarray]:
    if not mask.any():
        return []
    instances, _ = _collect_crack_instance_masks(mask)
    return instances


def _resize_bool_mask(mask: np.ndarray, size: int) -> np.ndarray:
    if mask.size == 0 or not mask.any():
        return np.zeros((size, size), dtype=bool)
    image = Image.fromarray((mask.astype(np.uint8) * 255), mode="L").resize(
        (size, size),
        NEAREST_RESAMPLE,
    )
    return np.array(image) > 0


def _crop_mask_for_shape(mask: np.ndarray, bbox: dict[str, int]) -> np.ndarray:
    if bbox["width"] <= 0 or bbox["height"] <= 0:
        return np.zeros((1, 1), dtype=bool)
    pad = max(2, int(max(bbox["width"], bbox["height"]) * 0.08))
    x1 = max(0, bbox["x"] - pad)
    y1 = max(0, bbox["y"] - pad)
    x2 = min(mask.shape[1], bbox["x"] + bbox["width"] + pad)
    y2 = min(mask.shape[0], bbox["y"] + bbox["height"] + pad)
    return mask[y1:y2, x1:x2]


def _pad_mask_to_square(mask: np.ndarray) -> np.ndarray:
    height, width = mask.shape
    side = max(height, width, 1)
    padded = np.zeros((side, side), dtype=bool)
    y_offset = (side - height) // 2
    x_offset = (side - width) // 2
    padded[y_offset : y_offset + height, x_offset : x_offset + width] = mask
    return padded


def _mask_orientation_deg(mask: np.ndarray) -> float:
    ys, xs = np.where(mask)
    if len(xs) < 2:
        return 0.0
    coords = np.column_stack((xs, ys)).astype(np.float64)
    centered = coords - coords.mean(axis=0)
    covariance = np.cov(centered, rowvar=False)
    if covariance.shape != (2, 2) or not np.isfinite(covariance).all():
        return 0.0
    values, vectors = np.linalg.eigh(covariance)
    major_vector = vectors[:, int(np.argmax(values))]
    angle = math.degrees(math.atan2(float(major_vector[1]), float(major_vector[0])))
    return angle % 180.0


def _build_mask_signature(mask: np.ndarray) -> MaskSignature:
    bbox = _mask_bbox(mask)
    ys, xs = np.where(mask)
    area_px = int(len(xs))
    if area_px == 0:
        return MaskSignature(
            bbox=bbox,
            area_px=0,
            centroid_x=0.0,
            centroid_y=0.0,
            orientation_deg=0.0,
            aspect_ratio=0.0,
            shape_bitmap=np.zeros((MASK_SHAPE_SIGNATURE_SIZE, MASK_SHAPE_SIGNATURE_SIZE), dtype=bool),
        )

    crop = _crop_mask_for_shape(mask, bbox)
    shape_bitmap = _resize_bool_mask(_pad_mask_to_square(crop), MASK_SHAPE_SIGNATURE_SIZE)
    return MaskSignature(
        bbox=bbox,
        area_px=area_px,
        centroid_x=float(xs.mean()),
        centroid_y=float(ys.mean()),
        orientation_deg=_mask_orientation_deg(mask),
        aspect_ratio=_component_elongation(bbox["width"], bbox["height"]),
        shape_bitmap=shape_bitmap,
    )


def _save_full_mask(mask: np.ndarray, path: Path) -> None:
    Image.fromarray((mask.astype(np.uint8) * 255), mode="L").save(path)


def _save_blue_overlay(frame_path: Path, mask: np.ndarray, output_path: Path, alpha: float = 0.45) -> None:
    with Image.open(frame_path) as image:
        rgb = np.array(image.convert("RGB")).astype(np.float32)
    blue = np.zeros_like(rgb)
    blue[..., 2] = 255.0
    overlay = rgb.copy()
    overlay[mask] = (1 - alpha) * overlay[mask] + alpha * blue[mask]
    Image.fromarray(np.clip(overlay, 0, 255).astype(np.uint8), mode="RGB").save(output_path)


def _ground_sampling_distance_m(
    *,
    image_width: int,
    image_height: int,
    rel_alt: float | None,
    focal_len: float | None,
    dzoom_ratio: float | None,
) -> tuple[float, float]:
    altitude_m = _corrected_relative_altitude_m(rel_alt)
    zoom_ratio = max(float(dzoom_ratio or 1.0), 1.0)
    effective_focal_mm = max(
        float(focal_len or 24.0) / (zoom_ratio**LANE_PROJECTION_CALIBRATION.dzoom_power),
        1.0,
    )
    ground_width_m = altitude_m * DJI_SENSOR_WIDTH_MM / effective_focal_mm
    ground_height_m = altitude_m * DJI_SENSOR_HEIGHT_MM / effective_focal_mm
    return ground_width_m / max(image_width, 1), ground_height_m / max(image_height, 1)


def _corrected_relative_altitude_m(rel_alt: float | None) -> float:
    raw_altitude_m = float(rel_alt or 0.0)
    calibrated_altitude_m = (
        raw_altitude_m * LANE_PROJECTION_CALIBRATION.altitude_scale
        + LANE_PROJECTION_CALIBRATION.altitude_offset_m
    )
    return max(calibrated_altitude_m, LANE_PROJECTION_CALIBRATION.min_altitude_m)


def _corrected_pitch_deg(pitch: float | None) -> float:
    return float(pitch if pitch is not None else -90.0) + LANE_PROJECTION_CALIBRATION.pitch_offset_deg


def _physical_focal_length_mm(focal_len: float | None, dzoom_ratio: float | None) -> float:
    focal_mm = float(focal_len or EQUIVALENT_FOCAL_MIN_MM)
    if FOCAL_LENGTH_IS_35MM_EQUIVALENT:
        focal_mm *= PHYSICAL_FOCAL_MIN_MM / EQUIVALENT_FOCAL_MIN_MM
    zoom_ratio = max(float(dzoom_ratio or 1.0), 1.0)
    effective_focal_mm = (
        focal_mm
        * LANE_PROJECTION_CALIBRATION.focal_scale
        / (zoom_ratio**LANE_PROJECTION_CALIBRATION.dzoom_power)
    )
    return max(effective_focal_mm, 1.0)


def _camera_intrinsics_px(
    *,
    image_width: int,
    image_height: int,
    focal_len: float | None,
    dzoom_ratio: float | None,
) -> tuple[float, float, float, float]:
    focal_mm = _physical_focal_length_mm(focal_len, dzoom_ratio)
    fx = focal_mm / DJI_SENSOR_WIDTH_MM * image_width
    fy = focal_mm / DJI_SENSOR_HEIGHT_MM * image_height
    cx = image_width / 2
    cy = image_height / 2
    return fx, fy, cx, cy


def _pixel_to_ground_xy(
    *,
    u: float,
    v: float,
    fx: float,
    fy: float,
    cx: float,
    cy: float,
    altitude_m: float,
    pitch_deg: float,
) -> tuple[float, float] | None:
    ray_x = (u - cx) / fx
    ray_y = (v - cy) / fy
    ray_z = 1.0

    # DJI gimbal pitch is -90 when the camera points straight down. Convert it
    # to a tilt angle around the image x-axis, then intersect each image ray
    # with the local flat road plane.
    tilt_rad = math.radians(pitch_deg + 90.0)
    cos_tilt = math.cos(tilt_rad)
    sin_tilt = math.sin(tilt_rad)
    ground_x_ray = ray_x
    ground_y_ray = ray_y * cos_tilt - ray_z * sin_tilt
    ground_z_ray = ray_y * sin_tilt + ray_z * cos_tilt

    if ground_z_ray <= 1e-6:
        return None

    scale = altitude_m / ground_z_ray
    return ground_x_ray * scale, ground_y_ray * scale


def _ground_points_for_pixels(
    pixels: list[tuple[float, float]],
    *,
    image_width: int,
    image_height: int,
    srt: SrtEntry,
) -> list[tuple[float, float]]:
    altitude_m = _corrected_relative_altitude_m(srt.rel_alt)
    pitch_deg = _corrected_pitch_deg(srt.pitch)
    fx, fy, cx, cy = _camera_intrinsics_px(
        image_width=image_width,
        image_height=image_height,
        focal_len=srt.focal_len,
        dzoom_ratio=srt.dzoom_ratio,
    )
    ground_points: list[tuple[float, float]] = []
    for u, v in pixels:
        point = _pixel_to_ground_xy(
            u=u,
            v=v,
            fx=fx,
            fy=fy,
            cx=cx,
            cy=cy,
            altitude_m=altitude_m,
            pitch_deg=pitch_deg,
        )
        if point is not None and math.isfinite(point[0]) and math.isfinite(point[1]):
            ground_points.append(point)
    return ground_points


def _polygon_area_m2(points: list[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    area = 0.0
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        area += point[0] * next_point[1] - next_point[0] * point[1]
    return abs(area) / 2


def _ground_area_for_pixel(
    *,
    x: int,
    y: int,
    image_width: int,
    image_height: int,
    srt: SrtEntry,
) -> float:
    points = _ground_points_for_pixels(
        [
            (float(x), float(y)),
            (float(x + 1), float(y)),
            (float(x + 1), float(y + 1)),
            (float(x), float(y + 1)),
        ],
        image_width=image_width,
        image_height=image_height,
        srt=srt,
    )
    if len(points) != 4:
        return 0.0
    return _polygon_area_m2(points)


def _ground_bbox_metrics(mask: np.ndarray, bbox: dict[str, int], srt: SrtEntry) -> dict[str, float]:
    height, width = mask.shape
    x1 = float(bbox["x"])
    y1 = float(bbox["y"])
    x2 = float(bbox["x"] + bbox["width"])
    y2 = float(bbox["y"] + bbox["height"])
    bbox_points = _ground_points_for_pixels(
        [(x1, y1), (x2, y1), (x2, y2), (x1, y2)],
        image_width=width,
        image_height=height,
        srt=srt,
    )
    if len(bbox_points) != 4:
        gsd_x, gsd_y = _ground_sampling_distance_m(
            image_width=width,
            image_height=height,
            rel_alt=srt.rel_alt,
            focal_len=_physical_focal_length_mm(srt.focal_len, srt.dzoom_ratio),
            dzoom_ratio=1.0,
        )
        bbox_width_m = bbox["width"] * gsd_x
        bbox_height_m = bbox["height"] * gsd_y
        area_m2 = int(mask.sum()) * gsd_x * gsd_y
        return {
            "bbox_width_m": bbox_width_m,
            "bbox_height_m": bbox_height_m,
            "length_m": max(bbox_width_m, bbox_height_m),
            "max_width_m": min(bbox_width_m, bbox_height_m),
            "area_m2": area_m2,
        }

    edges = [
        math.dist(bbox_points[0], bbox_points[1]),
        math.dist(bbox_points[1], bbox_points[2]),
        math.dist(bbox_points[2], bbox_points[3]),
        math.dist(bbox_points[3], bbox_points[0]),
    ]
    bbox_width_m = (edges[0] + edges[2]) / 2
    bbox_height_m = (edges[1] + edges[3]) / 2
    length_m = max(edges)
    max_width_m = min(edges)

    ys, xs = np.where(mask)
    if len(xs) == 0:
        area_m2 = 0.0
    else:
        sample_limit = 3000
        if len(xs) > sample_limit:
            indices = np.linspace(0, len(xs) - 1, sample_limit, dtype=int)
            xs_sample = xs[indices]
            ys_sample = ys[indices]
        else:
            xs_sample = xs
            ys_sample = ys
        sample_pixels = [(float(x) + 0.5, float(y) + 0.5) for x, y in zip(xs_sample, ys_sample)]
        sample_areas = [
            _ground_area_for_pixel(
                x=int(x),
                y=int(y),
                image_width=width,
                image_height=height,
                srt=srt,
            )
            for x, y in zip(xs_sample, ys_sample)
        ]
        valid_sample_areas = [area for area in sample_areas if area > 0 and math.isfinite(area)]
        if valid_sample_areas:
            area_m2 = sum(valid_sample_areas) / len(valid_sample_areas) * len(xs)
        else:
            sample_points = _ground_points_for_pixels(
                sample_pixels,
                image_width=width,
                image_height=height,
                srt=srt,
            )
            if len(sample_points) < 2:
                area_m2 = 0.0
            else:
                ground_xs = [point[0] for point in sample_points]
                ground_ys = [point[1] for point in sample_points]
                sample_area_m2 = (max(ground_xs) - min(ground_xs)) * (max(ground_ys) - min(ground_ys))
                area_m2 = max(sample_area_m2, 0.0) * len(xs) / max(len(sample_points), 1)

    return {
        "bbox_width_m": bbox_width_m,
        "bbox_height_m": bbox_height_m,
        "length_m": length_m,
        "max_width_m": max_width_m,
        "area_m2": area_m2,
    }


def _mask_bbox(mask: np.ndarray) -> dict[str, int]:
    ys, xs = np.where(mask)
    if len(xs) == 0 or len(ys) == 0:
        return {"x": 0, "y": 0, "width": 0, "height": 0}
    x1, x2 = int(xs.min()), int(xs.max())
    y1, y2 = int(ys.min()), int(ys.max())
    return {"x": x1, "y": y1, "width": x2 - x1 + 1, "height": y2 - y1 + 1}


def _estimate_crack_metrics(mask: np.ndarray, srt: SrtEntry) -> dict:
    height, width = mask.shape
    bbox = _mask_bbox(mask)
    area_px = int(mask.sum())
    if area_px <= 0:
        return {
            "bbox": bbox,
            "crack_type": "none",
            "severity_level": 0,
            "severity_label": "未检测到",
            "severity_score": 0.0,
            "length_m": 0.0,
            "avg_width_cm": 0.0,
            "max_width_cm": 0.0,
            "area_m2": 0.0,
        }

    ground_metrics = _ground_bbox_metrics(mask, bbox, srt)
    bbox_width_m = ground_metrics["bbox_width_m"]
    bbox_height_m = ground_metrics["bbox_height_m"]
    length_m = ground_metrics["length_m"]
    area_m2 = ground_metrics["area_m2"]
    avg_width_m = area_m2 / max(length_m, 1e-6)
    max_width_m = ground_metrics["max_width_m"]
    area_ratio = area_px / max(mask.size, 1)
    severity_level = 3 if area_ratio >= 0.01 or area_m2 >= 0.05 else 2 if area_ratio >= 0.003 or area_m2 >= 0.015 else 1
    crack_type = "longitudinal_crack" if bbox_height_m >= bbox_width_m else "transverse_crack"

    return {
        "bbox": bbox,
        "crack_type": crack_type,
        "severity_level": severity_level,
        "severity_label": {1: "轻微", 2: "中等", 3: "严重"}[severity_level],
        "severity_score": round(min(1.0, area_ratio * 25 + severity_level / 10), 4),
        "length_m": round(length_m, 3),
        "avg_width_cm": round(avg_width_m * 100, 2),
        "max_width_cm": round(max_width_m * 100, 2),
        "area_m2": round(area_m2, 4),
    }


def _count_severity(counts: dict[int, int], severity_level: int) -> None:
    counts[severity_level] = counts.get(severity_level, 0) + 1


def _distance_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    lat_scale = 111_320.0
    lon_scale = 111_320.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lon1 - lon2) * lon_scale, (lat1 - lat2) * lat_scale)


def _offset_lon_lat(longitude: float, latitude: float, east_m: float, north_m: float) -> tuple[float, float]:
    lat_scale = 111_320.0
    lon_scale = 111_320.0 * math.cos(math.radians(latitude))
    if abs(lon_scale) < 1e-6:
        return longitude, latitude
    return longitude + east_m / lon_scale, latitude + north_m / lat_scale


def _rotate_ground_offset_by_yaw(x_m: float, y_m: float, yaw_deg: float | None) -> tuple[float, float]:
    yaw_rad = math.radians(float(yaw_deg or 0.0))
    east_m = x_m * math.cos(yaw_rad) - y_m * math.sin(yaw_rad)
    north_m = x_m * math.sin(yaw_rad) + y_m * math.cos(yaw_rad)
    return east_m, north_m


def _estimate_crack_ground_position(
    signature: MaskSignature,
    srt: SrtEntry,
    image_width: int,
    image_height: int,
) -> tuple[float | None, float | None]:
    if srt.longitude is None or srt.latitude is None or signature.area_px <= 0:
        return srt.longitude, srt.latitude

    altitude_m = _corrected_relative_altitude_m(srt.rel_alt)
    pitch_deg = _corrected_pitch_deg(srt.pitch)
    fx, fy, cx, cy = _camera_intrinsics_px(
        image_width=image_width,
        image_height=image_height,
        focal_len=srt.focal_len,
        dzoom_ratio=srt.dzoom_ratio,
    )
    point = _pixel_to_ground_xy(
        u=signature.centroid_x,
        v=signature.centroid_y,
        fx=fx,
        fy=fy,
        cx=cx,
        cy=cy,
        altitude_m=altitude_m,
        pitch_deg=pitch_deg,
    )
    if point is None:
        return srt.longitude, srt.latitude

    east_m, north_m = _rotate_ground_offset_by_yaw(point[0], point[1], srt.yaw)
    return _offset_lon_lat(float(srt.longitude), float(srt.latitude), east_m, north_m)


def _bbox_similarity(a: dict, b: dict) -> float:
    ax1, ay1 = a["x"], a["y"]
    ax2, ay2 = ax1 + a["width"], ay1 + a["height"]
    bx1, by1 = b["x"], b["y"]
    bx2, by2 = bx1 + b["width"], by1 + b["height"]
    inter_w = max(0, min(ax2, bx2) - max(ax1, bx1))
    inter_h = max(0, min(ay2, by2) - max(ay1, by1))
    inter = inter_w * inter_h
    union = max(a["width"] * a["height"] + b["width"] * b["height"] - inter, 1)
    return inter / union


def _bitmap_iou(a: np.ndarray, b: np.ndarray) -> float:
    intersection = int(np.logical_and(a, b).sum())
    union = int(np.logical_or(a, b).sum())
    if union <= 0:
        return 0.0
    return intersection / union


def _bitmap_dice(a: np.ndarray, b: np.ndarray) -> float:
    intersection = int(np.logical_and(a, b).sum())
    total = int(a.sum() + b.sum())
    if total <= 0:
        return 0.0
    return 2 * intersection / total


def _angle_delta_deg(a: float, b: float) -> float:
    delta = abs(a - b) % 180.0
    return min(delta, 180.0 - delta)


def _centroid_distance_ratio(a: MaskSignature, b: MaskSignature) -> float:
    distance_px = math.hypot(a.centroid_x - b.centroid_x, a.centroid_y - b.centroid_y)
    bbox_diag = max(
        math.hypot(a.bbox["width"], a.bbox["height"]),
        math.hypot(b.bbox["width"], b.bbox["height"]),
        1.0,
    )
    return distance_px / bbox_diag


def _mask_signature_similarity(a: MaskSignature, b: MaskSignature) -> dict[str, float]:
    area_ratio = min(a.area_px, b.area_px) / max(a.area_px, b.area_px, 1)
    return {
        "bbox_iou": _bbox_similarity(a.bbox, b.bbox),
        "shape_iou": _bitmap_iou(a.shape_bitmap, b.shape_bitmap),
        "shape_dice": _bitmap_dice(a.shape_bitmap, b.shape_bitmap),
        "area_ratio": area_ratio,
        "center_distance_ratio": _centroid_distance_ratio(a, b),
        "orientation_delta": _angle_delta_deg(a.orientation_deg, b.orientation_deg),
    }


def _mask_signatures_match(existing: MaskSignature, candidate: MaskSignature) -> bool:
    if existing.area_px <= 0 or candidate.area_px <= 0:
        return False

    similarity = _mask_signature_similarity(existing, candidate)
    if (
        similarity["shape_iou"] >= CRACK_DEDUP_SHAPE_IOU_THRESHOLD
        and similarity["area_ratio"] >= 0.35
        and similarity["orientation_delta"] <= CRACK_DEDUP_ORIENTATION_DEGREES
    ):
        return True

    if (
        similarity["shape_dice"] >= CRACK_DEDUP_SHAPE_DICE_THRESHOLD
        and similarity["area_ratio"] >= 0.35
        and similarity["orientation_delta"] <= CRACK_DEDUP_ORIENTATION_DEGREES
    ):
        return True

    if (
        similarity["shape_dice"] >= 0.32
        and similarity["area_ratio"] >= 0.6
        and similarity["orientation_delta"] <= CRACK_DEDUP_ORIENTATION_DEGREES
    ):
        return True

    return False


def _pack_bool_bitmap(bitmap: np.ndarray) -> str:
    packed = np.packbits(bitmap.astype(np.uint8).reshape(-1))
    return base64.b64encode(packed.tobytes()).decode("ascii")


def _unpack_bool_bitmap(value: str, size: int) -> np.ndarray:
    raw = base64.b64decode(value.encode("ascii"))
    unpacked = np.unpackbits(np.frombuffer(raw, dtype=np.uint8))
    return unpacked[: size * size].reshape((size, size)).astype(bool)


def _signature_to_feature_dict(signature: MaskSignature) -> dict[str, object]:
    return {
        "version": 1,
        "area_px": signature.area_px,
        "orientation_deg": round(signature.orientation_deg, 3),
        "aspect_ratio": round(signature.aspect_ratio, 4),
        "shape_size": MASK_SHAPE_SIGNATURE_SIZE,
        "shape_bitmap": _pack_bool_bitmap(signature.shape_bitmap),
    }


def _signature_feature_hash(feature: dict[str, object]) -> str:
    payload = json.dumps(feature, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _signature_from_feature_json(feature_json: str | None) -> MaskSignature | None:
    if not feature_json:
        return None
    try:
        feature = json.loads(feature_json)
        size = int(feature.get("shape_size") or MASK_SHAPE_SIGNATURE_SIZE)
        shape_bitmap = _unpack_bool_bitmap(str(feature["shape_bitmap"]), size)
        return MaskSignature(
            bbox={"x": 0, "y": 0, "width": size, "height": size},
            area_px=int(feature.get("area_px") or 0),
            centroid_x=size / 2,
            centroid_y=size / 2,
            orientation_deg=float(feature.get("orientation_deg") or 0.0),
            aspect_ratio=float(feature.get("aspect_ratio") or 0.0),
            shape_bitmap=shape_bitmap,
        )
    except (KeyError, ValueError, TypeError, json.JSONDecodeError, binascii.Error):
        return None


def _priority_from_severity(severity_level: int, growth_area_m2: float = 0.0) -> str:
    if severity_level >= 3 or growth_area_m2 >= 0.02:
        return "高"
    if severity_level == 2 or growth_area_m2 >= 0.005:
        return "中"
    return "低"


def _identity_match_score(
    identity: models.CrackIdentity,
    record: DetectionRecord,
    road_segment: models.RoadSegment,
) -> tuple[float, dict[str, float]] | None:
    distance = _distance_m(
        float(identity.latest_longitude),
        float(identity.latest_latitude),
        record.longitude,
        record.latitude,
    )
    if distance > IDENTITY_CANDIDATE_DISTANCE_M:
        return None

    existing_signature = _signature_from_feature_json(identity.feature_json)
    existing_embedding_raw = _embedding_from_json(identity.embedding_json)
    record_embedding_raw = _safe_float_list(record.metrics.get("embedding"))
    existing_embedding = _normalize_embedding_vector(existing_embedding_raw) if existing_embedding_raw else None
    record_embedding = _normalize_embedding_vector(record_embedding_raw) if record_embedding_raw else None
    if existing_signature is None:
        area_a = float(identity.current_area_m2 or 0.0)
        area_b = float(record.metrics.get("area_m2") or 0.0)
        area_ratio = min(area_a, area_b) / max(area_a, area_b, 1e-6)
        shape_dice = 0.0
        shape_iou = 0.0
        orientation_delta = 0.0
    else:
        similarity = _mask_signature_similarity(existing_signature, record.mask_signature)
        area_ratio = similarity["area_ratio"]
        shape_dice = similarity["shape_dice"]
        shape_iou = similarity["shape_iou"]
        orientation_delta = similarity["orientation_delta"]

    embedding_similarity = _cosine_similarity(existing_embedding, record_embedding)
    road_bonus = 0.03 if identity.road_segment_id == road_segment.id else 0.015 if identity.road_name == road_segment.road_name else 0.0
    type_bonus = 0.05 if identity.crack_type == record.metrics.get("crack_type") else 0.0
    distance_score = max(0.0, 1.0 - distance / max(IDENTITY_GEO_SCORE_DISTANCE_M, 1e-6))
    shape_score = max(shape_dice, shape_iou)
    if existing_signature is not None and (
        shape_dice < IDENTITY_SHAPE_DICE_THRESHOLD
        or area_ratio < IDENTITY_AREA_RATIO_MIN
        or orientation_delta > IDENTITY_ORIENTATION_DEGREES
    ):
        if (embedding_similarity is None or embedding_similarity < CLASSIFIER_EMBEDDING_SIMILARITY_THRESHOLD) and distance > min(
            1.0,
            IDENTITY_MATCH_DISTANCE_M * 0.35,
        ):
            return None

    if embedding_similarity is not None:
        score = embedding_similarity * 0.7 + distance_score * 0.17 + max(shape_score, area_ratio) * 0.05 + type_bonus + road_bonus
    else:
        score = distance_score * 0.5 + shape_score * 0.28 + area_ratio * 0.12 + type_bonus + road_bonus
    details = {
        "distance_m": round(distance, 3),
        "shape_dice": round(shape_dice, 4),
        "shape_iou": round(shape_iou, 4),
        "area_ratio": round(area_ratio, 4),
        "orientation_delta": round(orientation_delta, 2),
        "embedding_similarity": round(float(embedding_similarity), 4) if embedding_similarity is not None else -1.0,
        "score": round(score, 4),
    }
    return score, details


def _find_matching_identity(
    db: Session,
    record: DetectionRecord,
    road_segment: models.RoadSegment,
) -> tuple[models.CrackIdentity | None, dict[str, float] | None]:
    lat_scale = 111_320.0
    lon_scale = max(111_320.0 * math.cos(math.radians(record.latitude)), 1e-6)
    lat_delta = IDENTITY_CANDIDATE_DISTANCE_M / lat_scale
    lon_delta = IDENTITY_CANDIDATE_DISTANCE_M / lon_scale
    candidates = (
        db.query(models.CrackIdentity)
        .filter(
            models.CrackIdentity.district == road_segment.district,
            models.CrackIdentity.lifecycle_status != "archived",
            models.CrackIdentity.latest_latitude.between(record.latitude - lat_delta, record.latitude + lat_delta),
            models.CrackIdentity.latest_longitude.between(record.longitude - lon_delta, record.longitude + lon_delta),
        )
        .all()
    )

    best_identity = None
    best_score = -1.0
    best_details = None
    for identity in candidates:
        result = _identity_match_score(identity, record, road_segment)
        if result is None:
            continue
        score, details = result
        if score > best_score:
            best_identity = identity
            best_score = score
            best_details = details

    if best_identity is None or best_score < 0.38:
        return None, best_details
    runner_up_score = -1.0
    for identity in candidates:
        if best_identity is not None and identity.id == best_identity.id:
            continue
        result = _identity_match_score(identity, record, road_segment)
        if result is None:
            continue
        score, _ = result
        if score > runner_up_score:
            runner_up_score = score
    if best_details is not None:
        best_details["margin"] = round(best_score - max(runner_up_score, 0.0), 4)
        embedding_similarity = float(best_details.get("embedding_similarity", -1.0))
        if embedding_similarity >= 0 and (
            embedding_similarity < CLASSIFIER_EMBEDDING_SIMILARITY_THRESHOLD
            or best_details["margin"] < CLASSIFIER_EMBEDDING_MARGIN_THRESHOLD
        ):
            return None, best_details
    return best_identity, best_details


def _create_crack_identity(
    db: Session,
    record: DetectionRecord,
    road_segment: models.RoadSegment,
    *,
    task_id: int,
    crack_index: int,
    original_uri: str,
    result_uri: str,
) -> models.CrackIdentity:
    metrics = record.metrics
    severity_level = int(metrics["severity_level"])
    feature = _signature_to_feature_dict(record.mask_signature)
    embedding = _normalize_embedding_vector(_safe_float_list(metrics.get("embedding")) or [])
    created_token = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    identity = models.CrackIdentity(
        identity_code=f"CID-PENDING-{created_token}-{crack_index:04d}",
        road_segment_id=road_segment.id,
        road_name=road_segment.road_name,
        district=road_segment.district,
        crack_type=metrics["crack_type"],
        lifecycle_status="active",
        maintenance_status="unrepaired",
        priority_level=_priority_from_severity(severity_level),
        observation_count=1,
        first_seen_at=record.detected_at,
        last_seen_at=record.detected_at,
        last_task_id=task_id,
        center_longitude=record.longitude,
        center_latitude=record.latitude,
        latest_longitude=record.longitude,
        latest_latitude=record.latitude,
        current_severity_level=severity_level,
        current_severity_label=metrics["severity_label"],
        current_severity_score=float(metrics["severity_score"]),
        current_length_m=float(metrics["length_m"]),
        current_avg_width_cm=float(metrics["avg_width_cm"]),
        current_max_width_cm=float(metrics["max_width_cm"]),
        current_area_m2=float(metrics["area_m2"]),
        max_severity_level=severity_level,
        max_area_m2=float(metrics["area_m2"]),
        latest_original_image_uri=original_uri,
        latest_result_image_uri=result_uri,
        feature_hash=_signature_feature_hash(feature),
        feature_json=json.dumps(feature, ensure_ascii=False, sort_keys=True),
        embedding_model=CLASSIFIER_EMBEDDING_MODEL_NAME if embedding else None,
        embedding_json=_embedding_to_json(embedding),
        embedding_count=1 if embedding else 0,
    )
    db.add(identity)
    db.flush()
    identity.identity_code = f"CID-{identity.id:06d}"
    return identity


def _update_crack_identity(
    identity: models.CrackIdentity,
    record: DetectionRecord,
    *,
    task_id: int,
    original_uri: str,
    result_uri: str,
    match_details: dict[str, float] | None,
) -> None:
    metrics = record.metrics
    old_area = float(identity.current_area_m2 or 0.0)
    old_length = float(identity.current_length_m or 0.0)
    area = float(metrics["area_m2"])
    length = float(metrics["length_m"])
    severity_level = int(metrics["severity_level"])
    count = int(identity.observation_count or 0) + 1

    identity.observation_count = count
    identity.last_seen_at = record.detected_at
    identity.last_task_id = task_id
    identity.latest_longitude = record.longitude
    identity.latest_latitude = record.latitude
    identity.center_longitude = (float(identity.center_longitude) * (count - 1) + record.longitude) / count
    identity.center_latitude = (float(identity.center_latitude) * (count - 1) + record.latitude) / count
    identity.crack_type = metrics["crack_type"]
    identity.current_severity_level = severity_level
    identity.current_severity_label = metrics["severity_label"]
    identity.current_severity_score = float(metrics["severity_score"])
    identity.current_length_m = length
    identity.current_avg_width_cm = float(metrics["avg_width_cm"])
    identity.current_max_width_cm = float(metrics["max_width_cm"])
    identity.current_area_m2 = area
    identity.max_severity_level = max(int(identity.max_severity_level or 1), severity_level)
    identity.max_area_m2 = max(float(identity.max_area_m2 or 0.0), area)
    identity.growth_area_m2 = round(area - old_area, 4)
    identity.growth_length_m = round(length - old_length, 3)
    identity.priority_level = _priority_from_severity(severity_level, identity.growth_area_m2)
    identity.latest_original_image_uri = original_uri
    identity.latest_result_image_uri = result_uri
    feature = _signature_to_feature_dict(record.mask_signature)
    identity.feature_hash = _signature_feature_hash(feature)
    identity.feature_json = json.dumps(feature, ensure_ascii=False, sort_keys=True)
    new_embedding = _normalize_embedding_vector(_safe_float_list(metrics.get("embedding")) or [])
    current_embedding = _embedding_from_json(identity.embedding_json)
    current_embedding_count = int(identity.embedding_count or 0)
    if new_embedding:
        if current_embedding and len(current_embedding) == len(new_embedding) and current_embedding_count > 0:
            mixed = [
                (old_value * current_embedding_count + new_value) / (current_embedding_count + 1)
                for old_value, new_value in zip(current_embedding, new_embedding)
            ]
            identity.embedding_json = _embedding_to_json(_normalize_embedding_vector(mixed))
            identity.embedding_count = current_embedding_count + 1
        else:
            identity.embedding_json = _embedding_to_json(new_embedding)
            identity.embedding_count = 1
        identity.embedding_model = CLASSIFIER_EMBEDDING_MODEL_NAME
    if match_details:
        identity.remark = f"最近匹配: distance={match_details.get('distance_m')}m, shape_dice={match_details.get('shape_dice')}"
    if identity.maintenance_status == "completed" and area > max(old_area * 0.4, 0.002):
        identity.lifecycle_status = "recurred"


def _record_score(record: DetectionRecord) -> tuple[int, float, float]:
    metrics = record.metrics
    return (
        int(metrics.get("severity_level") or 0),
        float(metrics.get("area_m2") or 0),
        float(metrics.get("length_m") or 0),
    )


def _looks_like_same_crack(existing: DetectionRecord, candidate: DetectionRecord) -> bool:
    if _distance_m(existing.longitude, existing.latitude, candidate.longitude, candidate.latitude) > CRACK_DEDUP_DISTANCE_M:
        return False
    time_gap = abs((candidate.detected_at - existing.detected_at).total_seconds())
    if time_gap > CRACK_DEDUP_TIME_SECONDS:
        return False
    return _mask_signatures_match(existing.mask_signature, candidate.mask_signature)


def _deduplicate_detection_records(records: list[DetectionRecord]) -> list[DetectionRecord]:
    if not records:
        return records

    deduped: list[DetectionRecord] = []
    for candidate in sorted(records, key=lambda item: item.detected_at):
        duplicate_index = None
        for index, existing in enumerate(deduped):
            if _looks_like_same_crack(existing, candidate):
                duplicate_index = index
                break
        if duplicate_index is None:
            deduped.append(candidate)
            continue
        if _record_score(candidate) > _record_score(deduped[duplicate_index]):
            deduped[duplicate_index] = candidate
    return deduped


def _task_uploaded_media(db: Session, task_id: int) -> list[models.MediaAsset]:
    return (
        db.query(models.MediaAsset)
        .filter(
            models.MediaAsset.task_id == task_id,
            models.MediaAsset.category == "uploaded",
        )
        .order_by(models.MediaAsset.created_at.asc())
        .all()
    )


def uploaded_srt_paths(media_assets: list[models.MediaAsset]) -> list[Path]:
    srt_paths: list[Path] = []
    for media in media_assets:
        path = Path(media.file_path)
        suffix = path.suffix.lower()
        original_suffix = Path(media.file_name).suffix.lower()
        if media.asset_type == "srt" or suffix in SRT_EXTENSIONS or original_suffix in SRT_EXTENSIONS:
            srt_paths.append(_media_path(media))
    return srt_paths


def _pair_uploaded_videos_and_srt(media_assets: list[models.MediaAsset]) -> list[VideoPair]:
    videos: dict[str, models.MediaAsset] = {}
    srts: dict[str, models.MediaAsset] = {}

    for media in media_assets:
        path = Path(media.file_path)
        suffix = path.suffix.lower()
        original_name = Path(media.file_name)
        stem = original_name.stem
        original_suffix = original_name.suffix.lower()
        if media.asset_type == "video" or suffix in VIDEO_EXTENSIONS:
            videos[stem] = media
        elif media.asset_type == "srt" or suffix in SRT_EXTENSIONS or original_suffix in SRT_EXTENSIONS:
            srts[stem] = media

    pairs: list[VideoPair] = []
    for stem, video in videos.items():
        srt = srts.get(stem)
        if not srt:
            continue
        pairs.append(VideoPair(video=video, srt=srt))

    if not pairs:
        raise FileNotFoundError("未找到可配对的视频和 SRT 文件，请上传同名 MP4/MOV 与 SRT。")
    return pairs


def _media_path(media: models.MediaAsset) -> Path:
    path = Path(media.file_path)
    if path.exists():
        return path
    return resolve_file_uri_to_path(media.file_uri)


def _copy_upload_to_work(media: models.MediaAsset, target_dir: Path) -> Path:
    source = _media_path(media)
    if not source.exists():
        raise FileNotFoundError(f"上传文件不存在: {media.file_name}")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{_safe_stem(Path(media.file_name).stem)}{source.suffix}"
    shutil.copy2(source, target)
    return target


def _register_frame_media(
    db: Session,
    task_id: int,
    frame_path: Path,
    overlay_path: Path,
    crack_index: int,
    detected_at: datetime | None,
) -> tuple[str, str]:
    base_name = f"task_{task_id:03d}_crack_{crack_index:04d}"
    copied_image = IMAGES_UPLOAD_DIR / f"{base_name}.png"
    copied_result = RESULTS_UPLOAD_DIR / f"{base_name}_overlay.png"
    shutil.copy2(frame_path, copied_image)
    shutil.copy2(overlay_path, copied_result)

    original_uri = f"/uploads/images/{copied_image.name}"
    result_uri = f"/uploads/results/{copied_result.name}"
    captured_at = detected_at or datetime.utcnow()

    db.add(
        models.MediaAsset(
            task_id=task_id,
            asset_type="image",
            category="original",
            file_name=copied_image.name,
            file_path=str(copied_image),
            file_uri=original_uri,
            mime_type=guess_mime_type(copied_image, default="image/png"),
            captured_at=captured_at,
        )
    )
    db.add(
        models.MediaAsset(
            task_id=task_id,
            asset_type="image",
            category="result",
            file_name=copied_result.name,
            file_path=str(copied_result),
            file_uri=result_uri,
            mime_type="image/png",
            captured_at=captured_at,
        )
    )
    return original_uri, result_uri


def _combine_record_masks(records: list[DetectionRecord]) -> np.ndarray:
    if not records:
        return np.zeros((1, 1), dtype=bool)

    with Image.open(records[0].frame_path) as image:
        width, height = image.size
    combined = np.zeros((height, width), dtype=bool)
    for record in records:
        try:
            with Image.open(record.mask_path) as mask_image:
                mask = np.array(mask_image.convert("L")) > 0
        except (FileNotFoundError, OSError, UnidentifiedImageError):
            continue
        if mask.shape != combined.shape:
            resized = Image.fromarray((mask.astype(np.uint8) * 255), mode="L").resize(
                (width, height),
                NEAREST_RESAMPLE,
            )
            mask = np.array(resized) > 0
        combined |= mask
    return combined


def _save_frame_artifacts(
    records: list[DetectionRecord],
    frame_masks_dir: Path,
    frame_overlays_dir: Path,
    frame_index: int,
) -> tuple[Path, Path]:
    if not records:
        raise ValueError("无法为没有裂缝记录的帧生成图像")

    frame = records[0].frame
    mask = _combine_record_masks(records)
    mask_path = frame_masks_dir / f"{frame.stem}_frame_{frame_index:04d}_mask.png"
    overlay_path = frame_overlays_dir / f"{frame.stem}_frame_{frame_index:04d}_overlay.png"
    _save_full_mask(mask, mask_path)
    _save_blue_overlay(frame.frame_path, mask, overlay_path)
    return mask_path, overlay_path


def _register_inspection_frame_media(
    db: Session,
    task_id: int,
    frame_path: Path,
    overlay_path: Path,
    mask_path: Path,
    frame_index: int,
    captured_at: datetime | None,
) -> tuple[str, str, str]:
    base_name = f"task_{task_id:03d}_frame_{frame_index:04d}"
    copied_image = IMAGES_UPLOAD_DIR / f"{base_name}.png"
    copied_result = RESULTS_UPLOAD_DIR / f"{base_name}_overlay.png"
    copied_mask = MASKS_UPLOAD_DIR / f"{base_name}_mask.png"
    shutil.copy2(frame_path, copied_image)
    shutil.copy2(overlay_path, copied_result)
    shutil.copy2(mask_path, copied_mask)

    original_uri = f"/uploads/images/{copied_image.name}"
    result_uri = f"/uploads/results/{copied_result.name}"
    mask_uri = f"/uploads/masks/{copied_mask.name}"
    media_captured_at = captured_at or datetime.utcnow()

    db.add(
        models.MediaAsset(
            task_id=task_id,
            asset_type="image",
            category="frame_original",
            file_name=copied_image.name,
            file_path=str(copied_image),
            file_uri=original_uri,
            mime_type=guess_mime_type(copied_image, default="image/png"),
            captured_at=media_captured_at,
        )
    )
    db.add(
        models.MediaAsset(
            task_id=task_id,
            asset_type="image",
            category="frame_result",
            file_name=copied_result.name,
            file_path=str(copied_result),
            file_uri=result_uri,
            mime_type="image/png",
            captured_at=media_captured_at,
        )
    )
    db.add(
        models.MediaAsset(
            task_id=task_id,
            asset_type="image",
            category="frame_mask",
            file_name=copied_mask.name,
            file_path=str(copied_mask),
            file_uri=mask_uri,
            mime_type="image/png",
            captured_at=media_captured_at,
        )
    )
    return original_uri, result_uri, mask_uri


def _group_records_by_frame(records: list[DetectionRecord]) -> list[tuple[str, list[DetectionRecord]]]:
    grouped: dict[str, list[DetectionRecord]] = {}
    for record in records:
        grouped.setdefault(record.frame.stem, []).append(record)
    return sorted(grouped.items(), key=lambda item: item[1][0].detected_at)


def _update_road_segment_center(road_segment: models.RoadSegment, longitudes: list[float], latitudes: list[float]) -> None:
    if not longitudes or not latitudes:
        return
    road_segment.center_longitude = sum(longitudes) / len(longitudes)
    road_segment.center_latitude = sum(latitudes) / len(latitudes)
    road_segment.start_longitude = longitudes[0]
    road_segment.start_latitude = latitudes[0]
    road_segment.end_longitude = longitudes[-1]
    road_segment.end_latitude = latitudes[-1]


def run_crackmamba_detection(db: Session, task_id: int, weight_name: str = "crack9k") -> dict:
    task = db.get(models.InspectionTask, task_id)
    if not task:
        raise ValueError("任务不存在")
    checkpoint = resolve_checkpoint(weight_name)

    uploaded_media = _task_uploaded_media(db, task_id)
    pairs = _pair_uploaded_videos_and_srt(uploaded_media)
    srt_paths = uploaded_srt_paths(uploaded_media)
    apply_task_location_from_srt_paths(db, task, srt_paths)
    db.commit()
    task = db.get(models.InspectionTask, task_id)
    if not task:
        raise ValueError("任务不存在")

    is_review_task = is_review_task_type(task.task_type)
    road_segment = db.get(models.RoadSegment, task.road_segment_id) if task.road_segment_id else None
    if road_segment is None and not is_review_task:
        road_segment = get_or_create_road_segment(db, task.road_name, task.district)
        task.road_segment_id = road_segment.id
        db.flush()
    if road_segment is None and task.road_name and task.district:
        road_segment = get_or_create_road_segment(db, task.road_name, task.district)
        task.road_segment_id = road_segment.id
        db.flush()
    identity_matching_enabled = road_segment is not None and is_review_task
    create_identity_enabled = road_segment is not None
    _set_task_progress(db, task_id, 8, "已读取上传视频和 SRT 文件")

    work_root = UPLOADS_DIR / "crackmamba" / f"task_{task_id:03d}"
    if work_root.exists():
        shutil.rmtree(work_root)
    uploads_dir = work_root / "uploaded"
    frames_dir = work_root / "frames"
    tiles_dir = work_root / "tiles"
    output_dir = work_root / "output"
    masks_dir = work_root / "full_masks"
    overlays_dir = work_root / "overlays"
    frame_masks_dir = work_root / "frame_masks"
    frame_overlays_dir = work_root / "frame_overlays"
    classifier_crops_dir = work_root / "classifier_crops"
    for directory in (
        uploads_dir,
        frames_dir,
        tiles_dir,
        output_dir,
        masks_dir,
        overlays_dir,
        frame_masks_dir,
        frame_overlays_dir,
        classifier_crops_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    all_frames: list[FrameMeta] = []
    for pair in pairs:
        video_path = _copy_upload_to_work(pair.video, uploads_dir)
        srt_path = _copy_upload_to_work(pair.srt, uploads_dir)
        srt_entries = parse_srt_file(srt_path)
        pair_frames_dir = frames_dir / _safe_stem(video_path.stem)
        all_frames.extend(_prepare_video_frames(video_path, srt_entries, pair_frames_dir))
        _set_task_progress(db, task_id, 20, f"已抽取 {len(all_frames)} 帧")

    if not all_frames:
        raise FileNotFoundError("未抽取到可用于检测的视频帧")

    _set_task_progress(db, task_id, 28, "正在切分图像块")
    _split_frames_into_tiles(all_frames, tiles_dir)
    _set_task_progress(db, task_id, 38, f"正在调用 CrackMamba 推理（{weight_name}）")
    batch_results = _run_crackmamba_batch(tiles_dir, output_dir, checkpoint)
    _set_task_progress(db, task_id, 72, "正在合并掩膜并计算裂缝指标")
    tile_masks_by_frame = _load_tile_masks(batch_results, output_dir)

    detection_records: list[DetectionRecord] = []

    total_frames = len(all_frames)
    next_record_id = 1
    for frame_index, frame in enumerate(all_frames, start=1):
        tile_masks = tile_masks_by_frame.get(frame.stem, {})
        if len(tile_masks) != 4:
            raise RuntimeError(f"帧 {frame.stem} 的四宫格推理结果不完整")

        full_mask = _stitch_full_mask(frame.frame_path, tile_masks)
        if not full_mask.any():
            continue
        full_mask, filter_stats = _filter_crack_mask(full_mask)
        if not full_mask.any():
            continue
        instance_masks = _split_crack_instance_masks(full_mask)
        for instance_index, instance_mask in enumerate(instance_masks, start=1):
            suffix = f"_c{instance_index:02d}" if len(instance_masks) > 1 else ""
            mask_path = masks_dir / f"{frame.stem}{suffix}_mask.png"
            overlay_path = overlays_dir / f"{frame.stem}{suffix}_overlay.png"
            _save_full_mask(instance_mask, mask_path)
            _save_blue_overlay(frame.frame_path, instance_mask, overlay_path)

            metrics = _estimate_crack_metrics(instance_mask, frame.srt)
            metrics["mask_filter"] = {
                **filter_stats,
                "instance_index": instance_index,
                "instance_count": len(instance_masks),
            }
            mask_signature = _build_mask_signature(instance_mask)
            longitude, latitude = _estimate_crack_ground_position(
                mask_signature,
                frame.srt,
                image_width=instance_mask.shape[1],
                image_height=instance_mask.shape[0],
            )
            if longitude is None or latitude is None or not math.isfinite(longitude) or not math.isfinite(latitude):
                raise ValueError(f"帧 {frame.stem} 缺少有效经纬度，无法入库或地图展示")

            detection_records.append(
                DetectionRecord(
                    record_id=next_record_id,
                    frame=frame,
                    frame_path=frame.frame_path,
                    mask_path=mask_path,
                    overlay_path=overlay_path,
                    metrics=metrics,
                    mask_signature=mask_signature,
                    longitude=float(longitude),
                    latitude=float(latitude),
                    detected_at=frame.srt.captured_at or datetime.utcnow(),
                )
            )
            next_record_id += 1
        progress = 72 + int(frame_index / max(total_frames, 1) * 12)
        _set_task_progress(db, task_id, progress, f"已分析 {frame_index}/{total_frames} 帧")

    before_dedup = len(detection_records)
    detection_records = _deduplicate_detection_records(detection_records)
    _set_task_progress(db, task_id, 88, f"去重完成：{before_dedup} 条候选合并为 {len(detection_records)} 条")

    classifier_items: list[dict[str, object]] = []
    for record in detection_records:
        bbox = record.metrics["bbox"]
        crop_path = classifier_crops_dir / f"{record.frame.stem}_r{record.record_id:04d}.jpg"
        try:
            with Image.open(record.mask_path) as mask_image:
                mask = np.array(mask_image.convert("L")) > 0
            _save_classifier_crop(record.frame_path, mask, bbox, crop_path)
        except (FileNotFoundError, OSError, UnidentifiedImageError):
            continue
        classifier_items.append(
            {
                "record_id": record.record_id,
                "image_path": str(crop_path),
                "bbox": bbox,
                "fallback_crack_type": _heuristic_crack_type(mask, record.frame.srt),
            }
        )

    if classifier_items:
        _set_task_progress(db, task_id, 90, "正在区分裂缝类型")
        try:
            predictions_by_id = _run_crack_classifier(classifier_items, work_root)
        except Exception:
            predictions_by_id = {}
        for record in detection_records:
            prediction = predictions_by_id.get(record.record_id)
            if not prediction:
                continue
            record.metrics["crack_type"] = str(prediction.get("predicted_class") or record.metrics["crack_type"])
            record.metrics["crack_type_confidence"] = float(prediction.get("confidence") or 0.0)
            record.metrics["crack_type_used_fallback"] = bool(prediction.get("used_fallback") or False)
            record.metrics["crack_type_fallback_reason"] = str(prediction.get("fallback_reason") or "")
            embedding = _safe_float_list(prediction.get("embedding"))
            if embedding:
                record.metrics["embedding"] = _normalize_embedding_vector(embedding)

    purge_existing_task_results(db, task_id)
    _set_task_progress(db, task_id, 92, "正在写入检测结果")

    severity_counts: dict[int, int] = {}
    seen_longitudes: list[float] = []
    seen_latitudes: list[float] = []

    frame_groups = _group_records_by_frame(detection_records)
    crack_index = 1
    for frame_index, (_, frame_records) in enumerate(frame_groups, start=1):
        frame_records.sort(key=lambda item: item.record_id)
        first_record = frame_records[0]
        frame_mask_path, frame_overlay_path = _save_frame_artifacts(
            frame_records,
            frame_masks_dir,
            frame_overlays_dir,
            frame_index,
        )
        frame_original_uri, frame_result_uri, frame_mask_uri = _register_inspection_frame_media(
            db,
            task.id,
            first_record.frame.frame_path,
            frame_overlay_path,
            frame_mask_path,
            frame_index,
            first_record.detected_at,
        )

        max_record = max(frame_records, key=_record_score)
        max_metrics = max_record.metrics
        frame_longitude = sum(item.longitude for item in frame_records) / len(frame_records)
        frame_latitude = sum(item.latitude for item in frame_records) / len(frame_records)
        inspection_frame = models.InspectionFrame(
            task_id=task.id,
            road_segment_id=road_segment.id if road_segment is not None else None,
            frame_code=f"FRM-{task.id:03d}-{frame_index:04d}",
            road_name=task.road_name,
            district=task.district,
            captured_at=first_record.detected_at,
            elapsed_seconds=float(first_record.frame.elapsed_seconds),
            longitude=frame_longitude,
            latitude=frame_latitude,
            original_image_uri=frame_original_uri,
            result_image_uri=frame_result_uri,
            mask_image_uri=frame_mask_uri,
            crack_count=len(frame_records),
            max_severity_level=int(max_metrics.get("severity_level") or 0),
            max_severity_label=str(max_metrics.get("severity_label") or "未检测到"),
            total_area_m2=round(sum(float(item.metrics.get("area_m2") or 0.0) for item in frame_records), 4),
            remark=f"CrackMamba 视频推理帧；elapsed={first_record.frame.elapsed_seconds:.2f}s",
        )
        db.add(inspection_frame)
        db.flush()

        for record in frame_records:
            metrics = record.metrics
            severity_level = int(metrics["severity_level"])
            _count_severity(severity_counts, severity_level)
            original_uri, result_uri = _register_frame_media(
                db,
                task.id,
                record.frame.frame_path,
                record.overlay_path,
                crack_index,
                record.detected_at,
            )

            identity = None
            match_details = None
            if identity_matching_enabled:
                identity, match_details = _find_matching_identity(db, record, road_segment)
                if identity is not None:
                    _update_crack_identity(
                        identity,
                        record,
                        task_id=task.id,
                        original_uri=original_uri,
                        result_uri=result_uri,
                        match_details=match_details,
                    )

            if identity is None and create_identity_enabled:
                identity = _create_crack_identity(
                    db,
                    record,
                    road_segment,
                    task_id=task.id,
                    crack_index=crack_index,
                    original_uri=original_uri,
                    result_uri=result_uri,
                )

            seen_longitudes.append(record.longitude)
            seen_latitudes.append(record.latitude)

            bbox = metrics["bbox"]
            db.add(
                models.CrackRecord(
                    identity_id=identity.id if identity is not None else None,
                    frame_id=inspection_frame.id,
                    task_id=task.id,
                    road_segment_id=road_segment.id if road_segment is not None else None,
                    crack_code=f"CRK-{task.id:03d}-{crack_index:04d}",
                    road_name=task.road_name,
                    district=task.district,
                    crack_type=metrics["crack_type"],
                    severity_level=severity_level,
                    severity_label=metrics["severity_label"],
                    severity_score=float(metrics["severity_score"]),
                    length_m=float(metrics["length_m"]),
                    avg_width_cm=float(metrics["avg_width_cm"]),
                    max_width_cm=float(metrics["max_width_cm"]),
                    area_m2=float(metrics["area_m2"]),
                    bbox_x=int(bbox["x"]),
                    bbox_y=int(bbox["y"]),
                    bbox_width=int(bbox["width"]),
                    bbox_height=int(bbox["height"]),
                    longitude=record.longitude,
                    latitude=record.latitude,
                    original_image_uri=original_uri,
                    result_image_uri=result_uri,
                    embedding_model=CLASSIFIER_EMBEDDING_MODEL_NAME if record.metrics.get("embedding") else None,
                    embedding_json=_embedding_to_json(_safe_float_list(record.metrics.get("embedding"))),
                    detected_at=record.detected_at,
                    remark=(
                        f"CrackMamba 视频推理；elapsed={record.frame.elapsed_seconds:.2f}s；"
                        f"rel_alt={record.frame.srt.rel_alt}; focal_len={record.frame.srt.focal_len}; "
                        f"dzoom_ratio={record.frame.srt.dzoom_ratio}"
                    ),
                )
            )
            crack_index += 1

    if road_segment is not None:
        _update_road_segment_center(road_segment, seen_longitudes, seen_latitudes)
    task.status = "finished"
    task.finished_at = datetime.utcnow()
    task.progress_percent = 100
    task.progress_message = "检测完成" if create_identity_enabled else "检测完成；未能建立裂缝身份档案"
    task.road_segment_id = road_segment.id if road_segment is not None else None
    db.commit()

    return {
        "task_id": task.id,
        "status": task.status,
        "crack_count": len(detection_records),
        "severe_count": severity_counts.get(3, 0),
        "medium_count": severity_counts.get(2, 0),
        "minor_count": severity_counts.get(1, 0),
    }
