#!/usr/bin/env python3
"""Fit DJI ground-projection correction parameters from lane-width samples."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.crack_config import load_crack_config  # noqa: E402
from app.services.srt_parser import SrtEntry, parse_srt_file  # noqa: E402


@dataclass(frozen=True)
class CameraModel:
    sensor_width_mm: float
    sensor_height_mm: float
    focal_length_is_35mm_equivalent: bool
    physical_focal_min_mm: float
    equivalent_focal_min_mm: float


@dataclass(frozen=True)
class CalibrationParams:
    focal_scale: float
    pitch_offset_deg: float
    altitude_offset_m: float
    dzoom_power: float = 1.0
    altitude_scale: float = 1.0
    min_altitude_m: float = 1.0


@dataclass(frozen=True)
class LaneSample:
    source_file: Path
    sample_id: int
    video: str
    srt_path: Path
    time_seconds: float
    image_width: int
    image_height: int
    lane_width_m: float
    left_point: tuple[float, float]
    right_point: tuple[float, float]
    horizontal_band: str
    vertical_band: str
    srt: SrtEntry


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fit lane-width correction parameters from annotate_lane_width.py JSON files."
    )
    parser.add_argument(
        "--samples",
        type=Path,
        nargs="+",
        default=None,
        help="Sample JSON files. Default: calibration/*.json except generated calibration outputs.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("calibration/lane_projection_calibration.json"),
        help="Where to write fitted parameters.",
    )
    parser.add_argument(
        "--predictions-output",
        type=Path,
        default=None,
        help="Optional CSV with per-sample predictions and residuals.",
    )
    parser.add_argument("--min-altitude-m", type=float, default=1.0)
    parser.add_argument("--focal-min", type=float, default=0.6)
    parser.add_argument("--focal-max", type=float, default=2.4)
    parser.add_argument("--pitch-min", type=float, default=-35.0)
    parser.add_argument("--pitch-max", type=float, default=8.0)
    parser.add_argument("--altitude-offset-min", type=float, default=-2.0)
    parser.add_argument("--altitude-offset-max", type=float, default=20.0)
    return parser.parse_args()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _frange(start: float, stop: float, step: float) -> Iterable[float]:
    value = start
    while value <= stop + step / 2:
        yield round(value, 10)
        value += step


def _safe_float(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


def _resolve_path(path: Path, base_dir: Path) -> Path:
    if path.is_absolute():
        return path
    if path.exists():
        return path
    candidate = base_dir / path
    if candidate.exists():
        return candidate
    return PROJECT_ROOT / path


def _default_sample_files() -> list[Path]:
    files = []
    for path in sorted((PROJECT_ROOT / "calibration").glob("*.json")):
        if path.name in {"lane_projection_calibration.json"}:
            continue
        if path.name.endswith("_predictions.json"):
            continue
        files.append(path)
    return files


def _match_srt_entry(entries: list[SrtEntry], time_seconds: float) -> SrtEntry:
    return min(
        entries,
        key=lambda entry: min(
            abs(entry.start_seconds - time_seconds),
            abs(entry.end_seconds - time_seconds),
        ),
    )


def load_samples(sample_files: list[Path]) -> list[LaneSample]:
    samples: list[LaneSample] = []
    srt_cache: dict[Path, list[SrtEntry]] = {}
    for sample_file in sample_files:
        payload = json.loads(sample_file.read_text(encoding="utf-8"))
        raw_srt_path = payload.get("srt_path")
        if not raw_srt_path:
            raise ValueError(f"{sample_file} does not contain srt_path.")
        srt_path = _resolve_path(Path(raw_srt_path), sample_file.parent)
        if srt_path not in srt_cache:
            srt_cache[srt_path] = parse_srt_file(srt_path)

        for item in payload.get("samples") or []:
            left = item.get("left_point") or []
            right = item.get("right_point") or []
            if len(left) != 2 or len(right) != 2:
                continue
            time_seconds = float(item["time_seconds"])
            samples.append(
                LaneSample(
                    source_file=sample_file,
                    sample_id=int(item["sample_id"]),
                    video=str(item.get("video") or payload.get("video", {}).get("name") or ""),
                    srt_path=srt_path,
                    time_seconds=time_seconds,
                    image_width=int(item["image_width"]),
                    image_height=int(item["image_height"]),
                    lane_width_m=float(item["lane_width_m"]),
                    left_point=(float(left[0]), float(left[1])),
                    right_point=(float(right[0]), float(right[1])),
                    horizontal_band=str(item.get("horizontal_band") or ""),
                    vertical_band=str(item.get("vertical_band") or ""),
                    srt=_match_srt_entry(srt_cache[srt_path], time_seconds),
                )
            )
    if not samples:
        raise ValueError("No calibration samples found.")
    return samples


def _base_physical_focal_mm(entry: SrtEntry, camera: CameraModel) -> float:
    focal_mm = float(entry.focal_len or camera.equivalent_focal_min_mm)
    if camera.focal_length_is_35mm_equivalent:
        focal_mm *= camera.physical_focal_min_mm / camera.equivalent_focal_min_mm
    return max(focal_mm, 1e-6)


def _effective_focal_mm(entry: SrtEntry, camera: CameraModel, params: CalibrationParams) -> float:
    dzoom_ratio = max(float(entry.dzoom_ratio or 1.0), 1.0)
    return max(
        _base_physical_focal_mm(entry, camera)
        * params.focal_scale
        / (dzoom_ratio**params.dzoom_power),
        1e-6,
    )


def _corrected_altitude_m(entry: SrtEntry, params: CalibrationParams) -> float:
    rel_alt = float(entry.rel_alt or 0.0)
    return max(rel_alt * params.altitude_scale + params.altitude_offset_m, params.min_altitude_m)


def _corrected_pitch_deg(entry: SrtEntry, params: CalibrationParams) -> float:
    return float(entry.pitch if entry.pitch is not None else -90.0) + params.pitch_offset_deg


def _pixel_to_ground_xy(
    *,
    u: float,
    v: float,
    sample: LaneSample,
    camera: CameraModel,
    params: CalibrationParams,
) -> tuple[float, float] | None:
    focal_mm = _effective_focal_mm(sample.srt, camera, params)
    fx = focal_mm / camera.sensor_width_mm * sample.image_width
    fy = focal_mm / camera.sensor_height_mm * sample.image_height
    cx = sample.image_width / 2
    cy = sample.image_height / 2
    ray_x = (u - cx) / fx
    ray_y = (v - cy) / fy
    ray_z = 1.0

    tilt_rad = math.radians(_corrected_pitch_deg(sample.srt, params) + 90.0)
    cos_tilt = math.cos(tilt_rad)
    sin_tilt = math.sin(tilt_rad)
    ground_x_ray = ray_x
    ground_y_ray = ray_y * cos_tilt - ray_z * sin_tilt
    ground_z_ray = ray_y * sin_tilt + ray_z * cos_tilt
    if ground_z_ray <= 1e-9:
        return None

    scale = _corrected_altitude_m(sample.srt, params) / ground_z_ray
    return ground_x_ray * scale, ground_y_ray * scale


def predict_lane_width_m(
    sample: LaneSample,
    camera: CameraModel,
    params: CalibrationParams,
) -> float | None:
    left = _pixel_to_ground_xy(
        u=sample.left_point[0],
        v=sample.left_point[1],
        sample=sample,
        camera=camera,
        params=params,
    )
    right = _pixel_to_ground_xy(
        u=sample.right_point[0],
        v=sample.right_point[1],
        sample=sample,
        camera=camera,
        params=params,
    )
    if left is None or right is None:
        return None
    return math.dist(left, right)


def prediction_rows(
    samples: list[LaneSample],
    camera: CameraModel,
    params: CalibrationParams,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sample in samples:
        predicted = predict_lane_width_m(sample, camera, params)
        if predicted is None:
            continue
        observed = sample.lane_width_m
        error_m = predicted - observed
        error_percent = error_m / observed * 100 if observed else 0.0
        rows.append(
            {
                "source_file": str(sample.source_file),
                "sample_id": sample.sample_id,
                "video": sample.video,
                "time_seconds": sample.time_seconds,
                "horizontal_band": sample.horizontal_band,
                "vertical_band": sample.vertical_band,
                "observed_lane_width_m": observed,
                "predicted_lane_width_m": predicted,
                "error_m": error_m,
                "error_percent": error_percent,
                "rel_alt": sample.srt.rel_alt,
                "corrected_altitude_m": _corrected_altitude_m(sample.srt, params),
                "pitch": sample.srt.pitch,
                "corrected_pitch_deg": _corrected_pitch_deg(sample.srt, params),
                "focal_len": sample.srt.focal_len,
                "dzoom_ratio": sample.srt.dzoom_ratio,
                "effective_focal_mm": _effective_focal_mm(sample.srt, camera, params),
            }
        )
    return rows


def summarize_predictions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    errors = [float(row["error_percent"]) for row in rows]
    if not errors:
        raise ValueError("No valid predictions.")
    absolute_errors = [abs(error) for error in errors]
    summary: dict[str, Any] = {
        "count": len(errors),
        "bias_percent": _safe_float(sum(errors) / len(errors), 4),
        "mae_percent": _safe_float(sum(absolute_errors) / len(absolute_errors), 4),
        "rmse_percent": _safe_float(math.sqrt(sum(error * error for error in errors) / len(errors)), 4),
        "max_abs_percent": _safe_float(max(absolute_errors), 4),
    }

    groups: dict[str, list[float]] = {}
    for row in rows:
        keys = [
            f"file:{Path(str(row['source_file'])).name}",
            f"band:{row['horizontal_band']}/{row['vertical_band']}",
            f"file_band:{Path(str(row['source_file'])).name}:{row['horizontal_band']}/{row['vertical_band']}",
        ]
        for key in keys:
            groups.setdefault(key, []).append(float(row["error_percent"]))

    summary["groups"] = {
        key: {
            "count": len(values),
            "bias_percent": _safe_float(sum(values) / len(values), 4),
            "mae_percent": _safe_float(sum(abs(value) for value in values) / len(values), 4),
            "min_percent": _safe_float(min(values), 4),
            "max_percent": _safe_float(max(values), 4),
        }
        for key, values in sorted(groups.items())
    }
    return summary


def score_params(samples: list[LaneSample], camera: CameraModel, params: CalibrationParams) -> float:
    rows = prediction_rows(samples, camera, params)
    if len(rows) != len(samples):
        return float("inf")
    return float(summarize_predictions(rows)["rmse_percent"])


def fit_params(samples: list[LaneSample], camera: CameraModel, args: argparse.Namespace) -> CalibrationParams:
    best_params = CalibrationParams(
        focal_scale=1.0,
        pitch_offset_deg=0.0,
        altitude_offset_m=0.0,
        min_altitude_m=args.min_altitude_m,
    )
    best_score = score_params(samples, camera, best_params)

    for focal_scale in _frange(args.focal_min, args.focal_max, 0.05):
        for pitch_offset in _frange(args.pitch_min, args.pitch_max, 1.0):
            for altitude_offset in _frange(args.altitude_offset_min, args.altitude_offset_max, 0.5):
                params = CalibrationParams(
                    focal_scale=focal_scale,
                    pitch_offset_deg=pitch_offset,
                    altitude_offset_m=altitude_offset,
                    min_altitude_m=args.min_altitude_m,
                )
                score = score_params(samples, camera, params)
                if score < best_score:
                    best_score = score
                    best_params = params

    refine_steps = [
        (0.01, 0.25, 0.1, 8),
        (0.002, 0.05, 0.02, 6),
    ]
    for focal_step, pitch_step, altitude_step, radius in refine_steps:
        start = best_params
        for focal_index in range(-radius, radius + 1):
            focal_scale = max(0.001, start.focal_scale + focal_index * focal_step)
            for pitch_index in range(-radius, radius + 1):
                pitch_offset = start.pitch_offset_deg + pitch_index * pitch_step
                for altitude_index in range(-radius, radius + 1):
                    altitude_offset = start.altitude_offset_m + altitude_index * altitude_step
                    params = CalibrationParams(
                        focal_scale=focal_scale,
                        pitch_offset_deg=pitch_offset,
                        altitude_offset_m=altitude_offset,
                        min_altitude_m=args.min_altitude_m,
                    )
                    score = score_params(samples, camera, params)
                    if score < best_score:
                        best_score = score
                        best_params = params

    return best_params


def _params_to_json(params: CalibrationParams) -> dict[str, float]:
    return {
        "focal_scale": _safe_float(params.focal_scale, 6),
        "dzoom_power": _safe_float(params.dzoom_power, 6),
        "pitch_offset_deg": _safe_float(params.pitch_offset_deg, 6),
        "altitude_scale": _safe_float(params.altitude_scale, 6),
        "altitude_offset_m": _safe_float(params.altitude_offset_m, 6),
        "min_altitude_m": _safe_float(params.min_altitude_m, 6),
    }


def write_predictions_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source_file",
        "sample_id",
        "video",
        "time_seconds",
        "horizontal_band",
        "vertical_band",
        "observed_lane_width_m",
        "predicted_lane_width_m",
        "error_m",
        "error_percent",
        "rel_alt",
        "corrected_altitude_m",
        "pitch",
        "corrected_pitch_deg",
        "focal_len",
        "dzoom_ratio",
        "effective_focal_mm",
    ]
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def main() -> None:
    args = parse_args()
    sample_files = args.samples or _default_sample_files()
    sample_files = [Path(path) for path in sample_files]
    if not sample_files:
        raise ValueError("No sample JSON files found.")

    config = load_crack_config()
    camera = CameraModel(
        sensor_width_mm=config.dji_camera.sensor_width_mm,
        sensor_height_mm=config.dji_camera.sensor_height_mm,
        focal_length_is_35mm_equivalent=config.dji_camera.focal_length_is_35mm_equivalent,
        physical_focal_min_mm=config.dji_camera.physical_focal_min_mm,
        equivalent_focal_min_mm=config.dji_camera.equivalent_focal_min_mm,
    )
    samples = load_samples(sample_files)

    default_params = CalibrationParams(
        focal_scale=1.0,
        pitch_offset_deg=0.0,
        altitude_offset_m=0.0,
        min_altitude_m=args.min_altitude_m,
    )
    fitted_params = fit_params(samples, camera, args)
    current_rows = prediction_rows(samples, camera, default_params)
    fitted_rows = prediction_rows(samples, camera, fitted_params)

    payload = {
        "schema_version": 1,
        "generated_at": _now_iso(),
        "sample_files": [str(path) for path in sample_files],
        "sample_count": len(samples),
        "camera": {
            "sensor_width_mm": camera.sensor_width_mm,
            "sensor_height_mm": camera.sensor_height_mm,
            "focal_length_is_35mm_equivalent": camera.focal_length_is_35mm_equivalent,
            "physical_focal_min_mm": camera.physical_focal_min_mm,
            "equivalent_focal_min_mm": camera.equivalent_focal_min_mm,
        },
        "model": {
            "effective_focal_mm": "physical_focal_mm * focal_scale / (dzoom_ratio ** dzoom_power)",
            "corrected_pitch_deg": "srt_pitch_deg + pitch_offset_deg",
            "corrected_altitude_m": "max(srt_rel_alt_m * altitude_scale + altitude_offset_m, min_altitude_m)",
        },
        "parameters": _params_to_json(fitted_params),
        "baseline_parameters": _params_to_json(default_params),
        "baseline_metrics": summarize_predictions(current_rows),
        "fitted_metrics": summarize_predictions(fitted_rows),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.predictions_output:
        write_predictions_csv(args.predictions_output, fitted_rows)

    print(json.dumps({
        "output": str(args.output),
        "sample_count": len(samples),
        "parameters": payload["parameters"],
        "baseline_mae_percent": payload["baseline_metrics"]["mae_percent"],
        "fitted_mae_percent": payload["fitted_metrics"]["mae_percent"],
        "fitted_rmse_percent": payload["fitted_metrics"]["rmse_percent"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
