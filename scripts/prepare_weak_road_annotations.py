#!/usr/bin/env python3
"""Create a time-separated annotation queue for the weakest road segments."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from annotate_crack_dataset import (  # noqa: E402
    QUADRANTS,
    QUADRANT_NAMES,
    Candidate,
    atomic_write_json,
    discover_videos,
    quadrant_bounds,
    safe_case_part,
)


DEFAULT_SEGMENTS = (
    "DJI_20260609164848_0004_Z_seg001",
    "DJI_20260609164848_0004_Z_seg003",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="为弱项道路生成训练/测试分离的标注任务清单。")
    parser.add_argument("--video-dir", type=Path, default=PROJECT_ROOT / "dji_videos" / "seg")
    parser.add_argument(
        "--base-manifest",
        type=Path,
        default=PROJECT_ROOT / "annotations" / "road_crack" / "annotation_manifest.json",
        help="已有标注清单，用于避开已经标注过的帧。",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=PROJECT_ROOT / "annotations" / "road_crack_weak"
    )
    parser.add_argument("--train-frames", type=int, default=8, help="每个弱项视频新增训练帧数。")
    parser.add_argument("--test-frames", type=int, default=4, help="每个弱项视频新增测试帧数。")
    parser.add_argument(
        "--segments", nargs="+", default=list(DEFAULT_SEGMENTS), help="要加标的视频片段 stem。"
    )
    parser.add_argument(
        "--min-gap-frames", type=int, default=30, help="新增帧及旧帧之间的最小间隔，默认约 1 秒。"
    )
    parser.add_argument("--force", action="store_true", help="覆盖尚未开始标注的新清单。")
    return parser.parse_args()


def load_existing_frames(path: Path) -> dict[str, set[int]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        segment: {int(item["frame_index"]) for item in payload.get("candidates", []) if item.get("segment") == segment}
        for segment in {item.get("segment") for item in payload.get("candidates", [])}
        if segment
    }


def select_spaced_frames(
    frame_count: int,
    start_ratio: float,
    end_ratio: float,
    count: int,
    forbidden: set[int],
    min_gap: int,
) -> list[int]:
    """Select deterministic interior frames, keeping a temporal buffer around old frames."""
    if count <= 0:
        return []
    start = max(0, round(frame_count * start_ratio))
    end = min(frame_count - 1, round(frame_count * end_ratio))
    available = [
        frame
        for frame in range(start, end + 1)
        if all(abs(frame - old) >= min_gap for old in forbidden)
    ]
    selected: list[int] = []
    for offset in range(count):
        target = round(start + (offset + 1) * (end - start) / (count + 1))
        options = sorted(available, key=lambda frame: (abs(frame - target), frame))
        chosen = next(
            (frame for frame in options if all(abs(frame - other) >= min_gap for other in selected)),
            None,
        )
        if chosen is None:
            raise RuntimeError(
                f"时间窗 {start}:{end} 中无法找到 {count} 个间隔 {min_gap} 帧的样本。"
            )
        selected.append(chosen)
        available.remove(chosen)
    return sorted(selected)


def build_weak_manifest(args: argparse.Namespace) -> dict:
    videos = {video.stem: video for video in discover_videos(args.video_dir)}
    missing = [segment for segment in args.segments if segment not in videos]
    if missing:
        raise FileNotFoundError("找不到弱项视频：" + "、".join(missing))
    existing = load_existing_frames(args.base_manifest)
    candidates: list[dict] = []
    plan: dict[str, dict[str, list[int]]] = {}
    for segment in args.segments:
        video = videos[segment]
        old_frames = existing.get(segment, set())
        train_frames = select_spaced_frames(
            video.frame_count, 0.05, 0.60, args.train_frames, old_frames, args.min_gap_frames
        )
        reserved = old_frames | set(train_frames)
        test_frames = select_spaced_frames(
            video.frame_count, 0.78, 0.95, args.test_frames, reserved, args.min_gap_frames
        )
        plan[segment] = {"train": train_frames, "test": test_frames}
        for dataset_split, frames, split_name, block_name in (
            ("train", train_frames, "新增训练集", "early_time_block"),
            ("test", test_frames, "新增测试集", "late_time_block"),
        ):
            for sample_number, frame_index in enumerate(frames, start=1):
                for quadrant in QUADRANTS:
                    x0, y0, x1, y1 = quadrant_bounds(video.width, video.height, quadrant)
                    candidate = Candidate(
                        id=f"{safe_case_part(video.stem)}_f{frame_index:06d}_{quadrant}",
                        video_path=video.path,
                        video_name=video.name,
                        segment=video.stem,
                        frame_index=frame_index,
                        time_seconds=round(frame_index / video.fps, 3),
                        sample_number=sample_number,
                        quadrant=quadrant,
                        quadrant_name=QUADRANT_NAMES[quadrant],
                        width=x1 - x0,
                        height=y1 - y0,
                    )
                    candidates.append(
                        {
                            **asdict(candidate),
                            "status": "pending",
                            "updated_at": None,
                            "dataset_split": dataset_split,
                            "split_name": split_name,
                            "temporal_block": block_name,
                            "annotation_set": "weak_road_adaptation",
                        }
                    )
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "annotation_manifest.json"
    if manifest_path.exists() and not args.force:
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        completed = sum(item.get("status") in {"annotated", "negative"} for item in old.get("candidates", []))
        if completed:
            raise RuntimeError("新任务已有完成标注，拒绝覆盖；如需继续请直接启动标注工具。")
        raise RuntimeError(f"清单已存在：{manifest_path}；确认后使用 --force 重建。")
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "schema_version": 1,
        "created_at": timestamp,
        "updated_at": timestamp,
        "annotation_set": "weak_road_adaptation",
        "annotation_title": "弱项道路加标（训练集 / 测试集）",
        "video_dir": str(args.video_dir.resolve()),
        "output_dir": str(output_dir),
        "base_manifest": str(args.base_manifest.resolve()),
        "segments": list(args.segments),
        "sampling_plan": plan,
        "train_frames_per_video": args.train_frames,
        "test_frames_per_video": args.test_frames,
        "min_gap_frames": args.min_gap_frames,
        "videos": [asdict(videos[segment]) for segment in args.segments],
        "candidates": candidates,
    }


def main() -> None:
    args = parse_args()
    if args.train_frames <= 0 or args.test_frames <= 0 or args.min_gap_frames < 0:
        raise SystemExit("帧数必须大于 0，最小间隔不能为负数。")
    manifest = build_weak_manifest(args)
    atomic_write_json(args.output_dir.resolve() / "annotation_manifest.json", manifest)
    atomic_write_json(
        args.output_dir.resolve() / "dataset.json",
        {
            "channel_names": {"0": "R", "1": "G", "2": "B"},
            "labels": {"background": 0, "crack": 1},
            "numTraining": 0,
            "file_ending": ".png",
            "name": "DJIRoadCrackWeakAdaptation",
            "overwrite_image_reader_writer": "NaturalImage2DIO",
        },
    )
    print(f"已生成 {len(manifest['candidates'])} 个待标图块：训练 {sum(x['dataset_split'] == 'train' for x in manifest['candidates'])}，测试 {sum(x['dataset_split'] == 'test' for x in manifest['candidates'])}。")
    for segment, split_plan in manifest["sampling_plan"].items():
        print(f"{segment}: train={split_plan['train']} test={split_plan['test']}")
    print(f"清单：{args.output_dir.resolve() / 'annotation_manifest.json'}")


if __name__ == "__main__":
    main()
