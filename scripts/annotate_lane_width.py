#!/usr/bin/env python3
"""Interactively annotate lane-width calibration samples on a video.

Example:
    python scripts/annotate_lane_width.py \
        --video dji_videos/DJI_20260609164611_0003_Z.MP4 \
        --srt dji_videos/DJI_20260609164611_0003_Z.SRT \
        --output calibration/lane_width_samples.json

Controls:
    left click   Add a lane boundary point. Two points define one sample.
    s            Save the current two-point sample.
    c            Clear current points.
    u            Remove the last saved sample.
    n / p        Jump forward/back by --step-sec seconds.
    . / ,        Jump forward/back by one frame.
    ] / [        Jump forward/back by one second.
    q / Esc      Save and quit.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import cv2
except ImportError as exc:  # pragma: no cover - depends on local conda env.
    raise SystemExit("OpenCV is required. Install opencv-python in the active conda env.") from exc


VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    fps: float
    frame_count: int
    width: int
    height: int

    @property
    def duration_seconds(self) -> float:
        if self.fps <= 0:
            return 0.0
        return self.frame_count / self.fps


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mark lane-width calibration samples on selected video frames."
    )
    parser.add_argument("--video", type=Path, required=True, help="Input video path.")
    parser.add_argument("--srt", type=Path, default=None, help="Optional matching DJI SRT path.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON path. Default: VIDEO_STEM_lane_width_samples.json beside the video.",
    )
    parser.add_argument(
        "--csv-output",
        type=Path,
        default=None,
        help="Optional CSV output path. It is rewritten after each saved sample.",
    )
    parser.add_argument("--lane-width-m", type=float, default=3.75, help="Real lane width in meters.")
    parser.add_argument("--start-sec", type=float, default=0.0, help="Initial video time in seconds.")
    parser.add_argument("--step-sec", type=float, default=5.0, help="n/p jump size in seconds.")
    parser.add_argument("--display-width", type=int, default=1280, help="Maximum display width.")
    parser.add_argument("--display-height", type=int, default=720, help="Maximum display height.")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Start a new annotation file even if --output already exists.",
    )
    return parser.parse_args()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _default_output_path(video_path: Path) -> Path:
    return video_path.with_name(f"{video_path.stem}_lane_width_samples.json")


def _safe_float(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


def _band(value: float, max_value: int, labels: tuple[str, str, str]) -> str:
    if max_value <= 0:
        return labels[1]
    ratio = value / max_value
    if ratio < 1 / 3:
        return labels[0]
    if ratio < 2 / 3:
        return labels[1]
    return labels[2]


def _sample_from_points(
    *,
    sample_id: int,
    video_info: VideoInfo,
    frame_index: int,
    points: list[tuple[int, int]],
    lane_width_m: float,
) -> dict[str, Any]:
    point_a, point_b = points
    left_point, right_point = sorted([point_a, point_b], key=lambda point: point[0])
    dx = point_b[0] - point_a[0]
    dy = point_b[1] - point_a[1]
    pixel_distance = math.hypot(dx, dy)
    if pixel_distance <= 0:
        raise ValueError("The two lane points must be different.")

    midpoint_x = (point_a[0] + point_b[0]) / 2
    midpoint_y = (point_a[1] + point_b[1]) / 2
    meters_per_pixel = lane_width_m / pixel_distance
    time_seconds = frame_index / video_info.fps if video_info.fps > 0 else 0.0

    return {
        "sample_id": sample_id,
        "video": video_info.path.name,
        "video_path": str(video_info.path),
        "frame_index": int(frame_index),
        "frame_number": int(frame_index + 1),
        "time_seconds": _safe_float(time_seconds, 3),
        "image_width": int(video_info.width),
        "image_height": int(video_info.height),
        "lane_width_m": _safe_float(lane_width_m, 4),
        "click_order_points": [[int(x), int(y)] for x, y in points],
        "left_point": [int(left_point[0]), int(left_point[1])],
        "right_point": [int(right_point[0]), int(right_point[1])],
        "pixel_distance": _safe_float(pixel_distance, 3),
        "meters_per_pixel": _safe_float(meters_per_pixel, 9),
        "millimeters_per_pixel": _safe_float(meters_per_pixel * 1000, 3),
        "midpoint": [_safe_float(midpoint_x, 2), _safe_float(midpoint_y, 2)],
        "normalized_midpoint": [
            _safe_float(midpoint_x / max(video_info.width, 1), 6),
            _safe_float(midpoint_y / max(video_info.height, 1), 6),
        ],
        "horizontal_band": _band(midpoint_x, video_info.width, ("left", "center", "right")),
        "vertical_band": _band(midpoint_y, video_info.height, ("top", "middle", "bottom")),
        "segment_angle_deg": _safe_float(math.degrees(math.atan2(dy, dx)), 3),
    }


def _open_video(video_path: Path) -> tuple[Any, VideoInfo]:
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")
    if video_path.suffix.lower() not in VIDEO_EXTENSIONS:
        print(f"Warning: {video_path.suffix} is not a common video extension.", file=sys.stderr)

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Failed to open video: {video_path}")

    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
        capture.release()
        raise RuntimeError(f"Video metadata is incomplete: {video_path}")
    return capture, VideoInfo(video_path, fps, frame_count, width, height)


def _read_frame(capture: Any, frame_index: int) -> Any:
    capture.set(cv2.CAP_PROP_POS_FRAMES, int(frame_index))
    ok, frame = capture.read()
    if not ok or frame is None:
        raise RuntimeError(f"Failed to read frame {frame_index}")
    return frame


def _load_existing_payload(path: Path, overwrite: bool) -> dict[str, Any] | None:
    if overwrite or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _build_payload(
    *,
    video_info: VideoInfo,
    srt_path: Path | None,
    lane_width_m: float,
    samples: list[dict[str, Any]],
    existing_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    created_at = (existing_payload or {}).get("created_at") or _now_iso()
    return {
        "schema_version": 1,
        "created_at": created_at,
        "updated_at": _now_iso(),
        "video": {
            "path": str(video_info.path),
            "name": video_info.path.name,
            "fps": _safe_float(video_info.fps, 6),
            "frame_count": video_info.frame_count,
            "duration_seconds": _safe_float(video_info.duration_seconds, 3),
            "width": video_info.width,
            "height": video_info.height,
        },
        "srt_path": str(srt_path) if srt_path else None,
        "default_lane_width_m": _safe_float(lane_width_m, 4),
        "sample_count": len(samples),
        "samples": samples,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, samples: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "sample_id",
        "video",
        "frame_index",
        "frame_number",
        "time_seconds",
        "image_width",
        "image_height",
        "lane_width_m",
        "left_x",
        "left_y",
        "right_x",
        "right_y",
        "pixel_distance",
        "meters_per_pixel",
        "millimeters_per_pixel",
        "midpoint_x",
        "midpoint_y",
        "horizontal_band",
        "vertical_band",
        "segment_angle_deg",
    ]
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        for sample in samples:
            writer.writerow(
                {
                    "sample_id": sample["sample_id"],
                    "video": sample["video"],
                    "frame_index": sample["frame_index"],
                    "frame_number": sample["frame_number"],
                    "time_seconds": sample["time_seconds"],
                    "image_width": sample["image_width"],
                    "image_height": sample["image_height"],
                    "lane_width_m": sample["lane_width_m"],
                    "left_x": sample["left_point"][0],
                    "left_y": sample["left_point"][1],
                    "right_x": sample["right_point"][0],
                    "right_y": sample["right_point"][1],
                    "pixel_distance": sample["pixel_distance"],
                    "meters_per_pixel": sample["meters_per_pixel"],
                    "millimeters_per_pixel": sample["millimeters_per_pixel"],
                    "midpoint_x": sample["midpoint"][0],
                    "midpoint_y": sample["midpoint"][1],
                    "horizontal_band": sample["horizontal_band"],
                    "vertical_band": sample["vertical_band"],
                    "segment_angle_deg": sample["segment_angle_deg"],
                }
            )


class LaneWidthAnnotator:
    def __init__(
        self,
        *,
        capture: Any,
        video_info: VideoInfo,
        srt_path: Path | None,
        output_path: Path,
        csv_output_path: Path | None,
        lane_width_m: float,
        start_seconds: float,
        step_seconds: float,
        display_width: int,
        display_height: int,
        existing_payload: dict[str, Any] | None,
    ) -> None:
        self.capture = capture
        self.video_info = video_info
        self.srt_path = srt_path
        self.output_path = output_path
        self.csv_output_path = csv_output_path
        self.lane_width_m = lane_width_m
        self.step_frames = max(1, int(round(step_seconds * video_info.fps)))
        self.one_second_frames = max(1, int(round(video_info.fps)))
        self.frame_index = self._clamp_frame(int(round(start_seconds * video_info.fps)))
        self.points: list[tuple[int, int]] = []
        self.samples: list[dict[str, Any]] = list((existing_payload or {}).get("samples") or [])
        self.existing_payload = existing_payload
        self.window_name = "Lane width annotator"
        self.last_message = "Click two lane boundary points, then press s."
        self.display_scale = min(
            display_width / max(video_info.width, 1),
            display_height / max(video_info.height, 1),
            1.0,
        )

    def _clamp_frame(self, frame_index: int) -> int:
        return max(0, min(int(frame_index), self.video_info.frame_count - 1))

    def _autosave(self) -> None:
        payload = _build_payload(
            video_info=self.video_info,
            srt_path=self.srt_path,
            lane_width_m=self.lane_width_m,
            samples=self.samples,
            existing_payload=self.existing_payload,
        )
        _write_json(self.output_path, payload)
        if self.csv_output_path:
            _write_csv(self.csv_output_path, self.samples)

    def _set_frame(self, frame_index: int) -> None:
        self.frame_index = self._clamp_frame(frame_index)
        self.points = []

    def _add_point_from_display(self, x: int, y: int) -> None:
        orig_x = self._clamp_coord(int(round(x / self.display_scale)), self.video_info.width)
        orig_y = self._clamp_coord(int(round(y / self.display_scale)), self.video_info.height)
        if len(self.points) >= 2:
            self.points = []
        self.points.append((orig_x, orig_y))
        self.last_message = f"Point {len(self.points)}/2: ({orig_x}, {orig_y})"

    @staticmethod
    def _clamp_coord(value: int, max_value: int) -> int:
        return max(0, min(value, max_value - 1))

    def _mouse_callback(self, event: int, x: int, y: int, flags: int, param: object) -> None:
        del flags, param
        if event == cv2.EVENT_LBUTTONDOWN:
            self._add_point_from_display(x, y)

    def _save_current_sample(self) -> None:
        if len(self.points) != 2:
            self.last_message = "Need exactly two points before saving."
            return
        sample = _sample_from_points(
            sample_id=len(self.samples) + 1,
            video_info=self.video_info,
            frame_index=self.frame_index,
            points=self.points,
            lane_width_m=self.lane_width_m,
        )
        self.samples.append(sample)
        self.points = []
        self._autosave()
        self.last_message = (
            f"Saved #{sample['sample_id']}: {sample['pixel_distance']:.1f}px, "
            f"{sample['millimeters_per_pixel']:.2f}mm/px"
        )

    def _undo_last_sample(self) -> None:
        if not self.samples:
            self.last_message = "No saved samples to undo."
            return
        removed = self.samples.pop()
        for index, sample in enumerate(self.samples, start=1):
            sample["sample_id"] = index
        self._autosave()
        self.last_message = f"Removed sample #{removed.get('sample_id')}"

    def _draw_overlay(self, frame: Any) -> Any:
        if self.display_scale < 1.0:
            frame = cv2.resize(
                frame,
                None,
                fx=self.display_scale,
                fy=self.display_scale,
                interpolation=cv2.INTER_AREA,
            )
        overlay = frame.copy()
        scale = self.display_scale

        for point in self.points:
            x = int(round(point[0] * scale))
            y = int(round(point[1] * scale))
            cv2.circle(overlay, (x, y), 5, (0, 255, 255), -1)
        if len(self.points) == 2:
            p1 = (int(round(self.points[0][0] * scale)), int(round(self.points[0][1] * scale)))
            p2 = (int(round(self.points[1][0] * scale)), int(round(self.points[1][1] * scale)))
            cv2.line(overlay, p1, p2, (0, 255, 255), 2)

        self._draw_text(overlay)
        return overlay

    def _draw_text(self, frame: Any) -> None:
        time_seconds = self.frame_index / self.video_info.fps
        lines = [
            f"{self.video_info.path.name}",
            (
                f"frame {self.frame_index + 1}/{self.video_info.frame_count}  "
                f"time {time_seconds:.3f}s  saved {len(self.samples)}"
            ),
            "left click: point | s: save | c: clear | u: undo | n/p: step | ./,: frame | ]/[: sec | q: quit",
            self.last_message,
        ]
        x, y = 12, 24
        for line in lines:
            cv2.putText(frame, line, (x + 1, y + 1), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3)
            cv2.putText(frame, line, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
            y += 24

    def run(self) -> None:
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(self.window_name, self._mouse_callback)
        print("Controls: click two lane boundaries, s save, n/p step, q quit.")
        print(f"Output JSON: {self.output_path}")
        if self.csv_output_path:
            print(f"Output CSV:  {self.csv_output_path}")

        while True:
            frame = _read_frame(self.capture, self.frame_index)
            cv2.imshow(self.window_name, self._draw_overlay(frame))
            key = cv2.waitKey(30) & 0xFF
            if key == 255:
                continue
            if key in (ord("q"), 27):
                self._autosave()
                break
            if key == ord("s"):
                self._save_current_sample()
            elif key == ord("c"):
                self.points = []
                self.last_message = "Cleared current points."
            elif key == ord("u"):
                self._undo_last_sample()
            elif key == ord("n"):
                self._set_frame(self.frame_index + self.step_frames)
            elif key == ord("p"):
                self._set_frame(self.frame_index - self.step_frames)
            elif key == ord("."):
                self._set_frame(self.frame_index + 1)
            elif key == ord(","):
                self._set_frame(self.frame_index - 1)
            elif key == ord("]"):
                self._set_frame(self.frame_index + self.one_second_frames)
            elif key == ord("["):
                self._set_frame(self.frame_index - self.one_second_frames)

        cv2.destroyWindow(self.window_name)


def main() -> None:
    args = parse_args()
    if args.lane_width_m <= 0:
        raise ValueError("--lane-width-m must be greater than 0.")
    if args.step_sec <= 0:
        raise ValueError("--step-sec must be greater than 0.")

    output_path = args.output or _default_output_path(args.video)
    existing_payload = _load_existing_payload(output_path, args.overwrite)
    capture, video_info = _open_video(args.video)
    try:
        annotator = LaneWidthAnnotator(
            capture=capture,
            video_info=video_info,
            srt_path=args.srt,
            output_path=output_path,
            csv_output_path=args.csv_output,
            lane_width_m=args.lane_width_m,
            start_seconds=args.start_sec,
            step_seconds=args.step_sec,
            display_width=args.display_width,
            display_height=args.display_height,
            existing_payload=existing_payload,
        )
        annotator.run()
    finally:
        capture.release()


if __name__ == "__main__":
    main()
