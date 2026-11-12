from __future__ import annotations

import configparser
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = BACKEND_ROOT / "crack_config.ini"
DEFAULT_CRACKMAMBA_ROOT = PROJECT_ROOT / "CrackMamba"


@dataclass(frozen=True)
class CrackMambaConfig:
    root: Path
    python: Path
    script: Path
    checkpoint: Path
    device: str
    batch_size: int


@dataclass(frozen=True)
class CrackClassifierConfig:
    enabled: bool
    python: Path
    script: Path
    checkpoint: Path
    device: str
    batch_size: int
    min_confidence: float
    embedding_enabled: bool
    embedding_model_name: str
    embedding_similarity_threshold: float
    embedding_margin_threshold: float


@dataclass(frozen=True)
class DetectionConfig:
    frame_sample_fps: float
    dedup_distance_m: float
    dedup_time_seconds: float
    dedup_shape_iou_threshold: float
    dedup_shape_dice_threshold: float
    dedup_center_distance_ratio: float
    dedup_orientation_degrees: float
    mask_min_area_px: int
    mask_noise_min_area_px: int
    mask_connect_gap_px: int
    mask_connect_line_width_px: int
    mask_min_component_area_px: int
    mask_min_component_length_px: int
    mask_min_component_elongation: float
    identity_match_distance_m: float
    identity_shape_dice_threshold: float
    identity_area_ratio_min: float
    identity_orientation_degrees: float
    identity_candidate_distance_m: float
    identity_geo_score_distance_m: float


@dataclass(frozen=True)
class DjiCameraConfig:
    sensor_width_mm: float
    sensor_height_mm: float
    focal_length_is_35mm_equivalent: bool
    physical_focal_min_mm: float
    equivalent_focal_min_mm: float


@dataclass(frozen=True)
class CrackConfig:
    path: Path
    crackmamba: CrackMambaConfig
    classifier: CrackClassifierConfig
    detection: DetectionConfig
    dji_camera: DjiCameraConfig


def _option_label(section: str, option: str) -> str:
    return f"[{section}].{option}"


def _get_text(
    parser: configparser.ConfigParser,
    section: str,
    option: str,
    default: str,
) -> str:
    if not parser.has_section(section) or not parser.has_option(section, option):
        return default

    value = parser.get(section, option).strip()
    return value or default


def _resolve_path(value: str, base_dir: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _get_executable(
    parser: configparser.ConfigParser,
    section: str,
    option: str,
    default: str,
) -> Path:
    value = _get_text(parser, section, option, default)
    path = Path(value).expanduser()
    if path.is_absolute() or path.parent != Path("."):
        return path.resolve()
    return Path(shutil.which(value) or value)


def _get_path(
    parser: configparser.ConfigParser,
    section: str,
    option: str,
    default: Path,
    *,
    base_dir: Path,
) -> Path:
    if not parser.has_section(section) or not parser.has_option(section, option):
        return default
    return _resolve_path(parser.get(section, option).strip() or str(default), base_dir)


def _get_float(
    parser: configparser.ConfigParser,
    section: str,
    option: str,
    default: float,
) -> float:
    raw_value = _get_text(parser, section, option, str(default))
    try:
        return float(raw_value)
    except ValueError as exc:
        raise ValueError(f"配置项 {_option_label(section, option)} 必须是数字，当前值: {raw_value}") from exc


def _get_int(
    parser: configparser.ConfigParser,
    section: str,
    option: str,
    default: int,
) -> int:
    raw_value = _get_text(parser, section, option, str(default))
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"配置项 {_option_label(section, option)} 必须是整数，当前值: {raw_value}") from exc


def _get_bool(
    parser: configparser.ConfigParser,
    section: str,
    option: str,
    default: bool,
) -> bool:
    raw_value = _get_text(parser, section, option, str(default)).lower()
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"配置项 {_option_label(section, option)} 必须是布尔值，当前值: {raw_value}")


def _ensure_greater_than(value: float, limit: float, section: str, option: str) -> None:
    if value <= limit:
        raise ValueError(f"配置项 {_option_label(section, option)} 必须大于 {limit}，当前值: {value}")


def _ensure_non_negative(value: float, section: str, option: str) -> None:
    if value < 0:
        raise ValueError(f"配置项 {_option_label(section, option)} 不能小于 0，当前值: {value}")


def _ensure_between(value: float, lower: float, upper: float, section: str, option: str) -> None:
    if value < lower or value > upper:
        raise ValueError(f"配置项 {_option_label(section, option)} 必须在 {lower} 到 {upper} 之间，当前值: {value}")


def load_crack_config(config_path: Path = DEFAULT_CONFIG_PATH) -> CrackConfig:
    parser = configparser.ConfigParser(
        interpolation=None,
        inline_comment_prefixes=("#",),
    )
    config_path = Path(config_path)
    if config_path.exists():
        try:
            parser.read(config_path, encoding="utf-8")
        except configparser.Error as exc:
            raise ValueError(f"配置文件解析失败: {config_path}: {exc}") from exc

    config_dir = config_path.parent
    crackmamba_root = _get_path(
        parser,
        "crackmamba",
        "root",
        DEFAULT_CRACKMAMBA_ROOT,
        base_dir=config_dir,
    )
    crackmamba_python = _get_executable(
        parser,
        "crackmamba",
        "python",
        sys.executable,
    )
    crackmamba_script = _get_path(
        parser,
        "crackmamba",
        "script",
        crackmamba_root / "tools" / "batch_infer_crack_images.py",
        base_dir=crackmamba_root,
    )
    crackmamba_checkpoint = _get_path(
        parser,
        "crackmamba",
        "checkpoint",
        crackmamba_root / "CrackSeg9k_checkpoint_best.pth",
        base_dir=crackmamba_root,
    )
    crackmamba_device = _get_text(parser, "crackmamba", "device", "cuda")
    crackmamba_batch_size = _get_int(parser, "crackmamba", "batch_size", 2)

    classifier_enabled = _get_bool(parser, "classifier", "enabled", True)
    classifier_python = _get_path(
        parser,
        "classifier",
        "python",
        crackmamba_python,
        base_dir=config_dir,
    )
    classifier_script = _get_path(
        parser,
        "classifier",
        "script",
        PROJECT_ROOT / "scripts" / "classify_crack_crops.py",
        base_dir=config_dir,
    )
    classifier_checkpoint = _get_path(
        parser,
        "classifier",
        "checkpoint",
        PROJECT_ROOT / "models" / "uapd_crack_classifier_efficientnet_v2_s.pt",
        base_dir=config_dir,
    )
    classifier_device = _get_text(parser, "classifier", "device", crackmamba_device)
    classifier_batch_size = _get_int(parser, "classifier", "batch_size", 16)
    classifier_min_confidence = _get_float(parser, "classifier", "min_confidence", 0.55)
    classifier_embedding_enabled = _get_bool(parser, "classifier", "embedding_enabled", True)
    classifier_embedding_model_name = _get_text(parser, "classifier", "embedding_model_name", "efficientnet_penultimate")
    classifier_embedding_similarity_threshold = _get_float(
        parser,
        "classifier",
        "embedding_similarity_threshold",
        0.8,
    )
    classifier_embedding_margin_threshold = _get_float(
        parser,
        "classifier",
        "embedding_margin_threshold",
        0.05,
    )

    frame_sample_fps = _get_float(parser, "detection", "frame_sample_fps", 2.0)
    dedup_distance_m = _get_float(parser, "detection", "dedup_distance_m", 1.0)
    dedup_time_seconds = _get_float(parser, "detection", "dedup_time_seconds", 2.0)
    dedup_shape_iou_threshold = _get_float(
        parser,
        "detection",
        "dedup_shape_iou_threshold",
        _get_float(parser, "detection", "dedup_mask_iou_threshold", 0.18),
    )
    dedup_shape_dice_threshold = _get_float(parser, "detection", "dedup_shape_dice_threshold", 0.48)
    dedup_center_distance_ratio = _get_float(parser, "detection", "dedup_center_distance_ratio", 0.45)
    dedup_orientation_degrees = _get_float(parser, "detection", "dedup_orientation_degrees", 45.0)
    mask_min_area_px = _get_int(parser, "detection", "mask_min_area_px", 24)
    mask_noise_min_area_px = _get_int(parser, "detection", "mask_noise_min_area_px", 6)
    mask_connect_gap_px = _get_int(parser, "detection", "mask_connect_gap_px", 32)
    mask_connect_line_width_px = _get_int(parser, "detection", "mask_connect_line_width_px", 3)
    mask_min_component_area_px = _get_int(parser, "detection", "mask_min_component_area_px", 16)
    mask_min_component_length_px = _get_int(parser, "detection", "mask_min_component_length_px", 12)
    mask_min_component_elongation = _get_float(parser, "detection", "mask_min_component_elongation", 1.6)
    identity_match_distance_m = _get_float(parser, "detection", "identity_match_distance_m", 3.0)
    identity_shape_dice_threshold = _get_float(parser, "detection", "identity_shape_dice_threshold", 0.42)
    identity_area_ratio_min = _get_float(parser, "detection", "identity_area_ratio_min", 0.25)
    identity_orientation_degrees = _get_float(parser, "detection", "identity_orientation_degrees", 55.0)
    identity_candidate_distance_m = _get_float(parser, "detection", "identity_candidate_distance_m", 12.0)
    identity_geo_score_distance_m = _get_float(parser, "detection", "identity_geo_score_distance_m", 6.0)

    sensor_width_mm = _get_float(parser, "dji_camera", "sensor_width_mm", 6.4)
    sensor_height_mm = _get_float(parser, "dji_camera", "sensor_height_mm", 3.6)
    focal_length_is_35mm_equivalent = _get_bool(
        parser,
        "dji_camera",
        "focal_length_is_35mm_equivalent",
        True,
    )
    physical_focal_min_mm = _get_float(parser, "dji_camera", "physical_focal_min_mm", 21.0)
    equivalent_focal_min_mm = _get_float(parser, "dji_camera", "equivalent_focal_min_mm", 113.0)

    _ensure_greater_than(frame_sample_fps, 0, "detection", "frame_sample_fps")
    _ensure_non_negative(dedup_distance_m, "detection", "dedup_distance_m")
    _ensure_non_negative(dedup_time_seconds, "detection", "dedup_time_seconds")
    _ensure_between(dedup_shape_iou_threshold, 0, 1, "detection", "dedup_shape_iou_threshold")
    _ensure_between(dedup_shape_dice_threshold, 0, 1, "detection", "dedup_shape_dice_threshold")
    _ensure_between(dedup_center_distance_ratio, 0, 2, "detection", "dedup_center_distance_ratio")
    _ensure_between(dedup_orientation_degrees, 0, 90, "detection", "dedup_orientation_degrees")
    _ensure_non_negative(mask_min_area_px, "detection", "mask_min_area_px")
    _ensure_non_negative(mask_noise_min_area_px, "detection", "mask_noise_min_area_px")
    _ensure_non_negative(mask_connect_gap_px, "detection", "mask_connect_gap_px")
    _ensure_greater_than(mask_connect_line_width_px, 0, "detection", "mask_connect_line_width_px")
    _ensure_non_negative(mask_min_component_area_px, "detection", "mask_min_component_area_px")
    _ensure_non_negative(mask_min_component_length_px, "detection", "mask_min_component_length_px")
    _ensure_greater_than(mask_min_component_elongation, 0, "detection", "mask_min_component_elongation")
    _ensure_non_negative(identity_match_distance_m, "detection", "identity_match_distance_m")
    _ensure_between(identity_shape_dice_threshold, 0, 1, "detection", "identity_shape_dice_threshold")
    _ensure_between(identity_area_ratio_min, 0, 1, "detection", "identity_area_ratio_min")
    _ensure_between(identity_orientation_degrees, 0, 90, "detection", "identity_orientation_degrees")
    _ensure_non_negative(identity_candidate_distance_m, "detection", "identity_candidate_distance_m")
    _ensure_non_negative(identity_geo_score_distance_m, "detection", "identity_geo_score_distance_m")
    _ensure_greater_than(crackmamba_batch_size, 0, "crackmamba", "batch_size")
    _ensure_greater_than(classifier_batch_size, 0, "classifier", "batch_size")
    _ensure_between(classifier_min_confidence, 0, 1, "classifier", "min_confidence")
    _ensure_between(
        classifier_embedding_similarity_threshold,
        -1,
        1,
        "classifier",
        "embedding_similarity_threshold",
    )
    _ensure_between(
        classifier_embedding_margin_threshold,
        0,
        1,
        "classifier",
        "embedding_margin_threshold",
    )
    _ensure_greater_than(sensor_width_mm, 0, "dji_camera", "sensor_width_mm")
    _ensure_greater_than(sensor_height_mm, 0, "dji_camera", "sensor_height_mm")
    _ensure_greater_than(physical_focal_min_mm, 0, "dji_camera", "physical_focal_min_mm")
    _ensure_greater_than(equivalent_focal_min_mm, 0, "dji_camera", "equivalent_focal_min_mm")

    if not crackmamba_device:
        raise ValueError("配置项 [crackmamba].device 不能为空")
    if classifier_enabled and not classifier_device:
        raise ValueError("配置项 [classifier].device 不能为空")

    return CrackConfig(
        path=config_path,
        crackmamba=CrackMambaConfig(
            root=crackmamba_root,
            python=crackmamba_python,
            script=crackmamba_script,
            checkpoint=crackmamba_checkpoint,
            device=crackmamba_device,
            batch_size=crackmamba_batch_size,
        ),
        classifier=CrackClassifierConfig(
            enabled=classifier_enabled,
            python=classifier_python,
            script=classifier_script,
            checkpoint=classifier_checkpoint,
            device=classifier_device,
            batch_size=classifier_batch_size,
            min_confidence=classifier_min_confidence,
            embedding_enabled=classifier_embedding_enabled,
            embedding_model_name=classifier_embedding_model_name,
            embedding_similarity_threshold=classifier_embedding_similarity_threshold,
            embedding_margin_threshold=classifier_embedding_margin_threshold,
        ),
        detection=DetectionConfig(
            frame_sample_fps=frame_sample_fps,
            dedup_distance_m=dedup_distance_m,
            dedup_time_seconds=dedup_time_seconds,
            dedup_shape_iou_threshold=dedup_shape_iou_threshold,
            dedup_shape_dice_threshold=dedup_shape_dice_threshold,
            dedup_center_distance_ratio=dedup_center_distance_ratio,
            dedup_orientation_degrees=dedup_orientation_degrees,
            mask_min_area_px=mask_min_area_px,
            mask_noise_min_area_px=mask_noise_min_area_px,
            mask_connect_gap_px=mask_connect_gap_px,
            mask_connect_line_width_px=mask_connect_line_width_px,
            mask_min_component_area_px=mask_min_component_area_px,
            mask_min_component_length_px=mask_min_component_length_px,
            mask_min_component_elongation=mask_min_component_elongation,
            identity_match_distance_m=identity_match_distance_m,
            identity_shape_dice_threshold=identity_shape_dice_threshold,
            identity_area_ratio_min=identity_area_ratio_min,
            identity_orientation_degrees=identity_orientation_degrees,
            identity_candidate_distance_m=identity_candidate_distance_m,
            identity_geo_score_distance_m=identity_geo_score_distance_m,
        ),
        dji_camera=DjiCameraConfig(
            sensor_width_mm=sensor_width_mm,
            sensor_height_mm=sensor_height_mm,
            focal_length_is_35mm_equivalent=focal_length_is_35mm_equivalent,
            physical_focal_min_mm=physical_focal_min_mm,
            equivalent_focal_min_mm=equivalent_focal_min_mm,
        ),
    )
