#!/usr/bin/env python3
"""Split DJI videos and matching SRT files into fixed-duration segments.

Defaults are chosen for this repository:

    python scripts/split_dji_videos.py

This reads videos in dji_videos/, writes segments to dji_videos/seg/, and
creates one re-timed SRT file per video segment.
"""

from __future__ import annotations

import argparse
import math
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


TIME_RE = re.compile(
    r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})"
)


@dataclass(frozen=True)
class SubtitleCue:
    start_ms: int
    end_ms: int
    lines: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Split videos and matching SRT subtitles into fixed segments."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("dji_videos"),
        help="Directory containing source videos and matching SRT files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for segmented outputs. Default: INPUT_DIR/seg.",
    )
    parser.add_argument(
        "--segment-seconds",
        type=float,
        default=30.0,
        help="Segment duration in seconds.",
    )
    parser.add_argument(
        "--mode",
        choices=("reencode", "copy"),
        default="reencode",
        help=(
            "Video split mode. reencode is slower but gives accurate boundaries; "
            "copy is faster but may align to keyframes."
        ),
    )
    parser.add_argument(
        "--crf",
        type=int,
        default=18,
        help="x264 CRF used when --mode reencode.",
    )
    parser.add_argument(
        "--preset",
        default="veryfast",
        help="x264 preset used when --mode reencode.",
    )
    parser.add_argument(
        "--video-ext",
        nargs="+",
        default=[".mp4", ".mov", ".m4v"],
        help="Video extensions to process.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing segment files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned outputs without writing files.",
    )
    return parser.parse_args()


def require_command(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Required command not found: {name}")


def run(cmd: list[str], dry_run: bool = False) -> None:
    if dry_run:
        print("DRY-RUN:", " ".join(cmd))
        return
    subprocess.run(cmd, check=True)


def ffprobe_duration(path: Path) -> float:
    raw = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        text=True,
    ).strip()
    return float(raw)


def parse_timestamp(value: str) -> int:
    hms, ms = value.split(",")
    hours, minutes, seconds = (int(part) for part in hms.split(":"))
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + int(ms)


def format_timestamp(ms: int) -> str:
    ms = max(0, ms)
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def parse_srt(path: Path) -> list[SubtitleCue]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []

    cues: list[SubtitleCue] = []
    for block in re.split(r"\n\s*\n", text):
        lines = block.split("\n")
        time_idx = -1
        match: re.Match[str] | None = None
        for idx, line in enumerate(lines):
            match = TIME_RE.search(line)
            if match:
                time_idx = idx
                break
        if time_idx < 0 or match is None:
            continue

        start_ms = parse_timestamp(match.group(1))
        end_ms = parse_timestamp(match.group(2))
        if end_ms <= start_ms:
            continue
        cues.append(SubtitleCue(start_ms, end_ms, lines[time_idx + 1 :]))
    return cues


def write_segment_srt(
    cues: Iterable[SubtitleCue],
    output_path: Path,
    segment_start_ms: int,
    segment_end_ms: int,
    dry_run: bool = False,
) -> int:
    blocks: list[str] = []

    for cue in cues:
        if cue.end_ms <= segment_start_ms or cue.start_ms >= segment_end_ms:
            continue

        clipped_start = max(cue.start_ms, segment_start_ms) - segment_start_ms
        clipped_end = min(cue.end_ms, segment_end_ms) - segment_start_ms
        if clipped_end <= clipped_start:
            continue

        blocks.append(
            "\n".join(
                [
                    str(len(blocks) + 1),
                    f"{format_timestamp(clipped_start)} --> {format_timestamp(clipped_end)}",
                    *cue.lines,
                ]
            )
        )

    if not dry_run:
        output_path.write_text(
            "\n\n".join(blocks) + ("\n" if blocks else ""), encoding="utf-8"
        )

    return len(blocks)


def find_matching_srt(video_path: Path) -> Path | None:
    exact_candidates = [
        video_path.with_suffix(".SRT"),
        video_path.with_suffix(".srt"),
    ]
    for candidate in exact_candidates:
        if candidate.exists():
            return candidate

    wanted = video_path.stem.lower()
    for candidate in video_path.parent.iterdir():
        if candidate.is_file() and candidate.suffix.lower() == ".srt":
            if candidate.stem.lower() == wanted:
                return candidate
    return None


def iter_videos(input_dir: Path, output_dir: Path, extensions: Iterable[str]) -> list[Path]:
    allowed = {ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in extensions}
    videos: list[Path] = []
    for path in sorted(input_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in allowed:
            continue
        try:
            path.relative_to(output_dir)
            continue
        except ValueError:
            videos.append(path)
    return videos


def build_ffmpeg_cmd(
    source: Path,
    output: Path,
    start_seconds: float,
    duration_seconds: float,
    args: argparse.Namespace,
) -> list[str]:
    base = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y" if args.overwrite else "-n",
        "-ss",
        f"{start_seconds:.3f}",
        "-i",
        str(source),
        "-t",
        f"{duration_seconds:.3f}",
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
    ]

    if args.mode == "copy":
        return [*base, "-c:v", "copy", str(output)]

    return [
        *base,
        "-c:v",
        "libx264",
        "-preset",
        args.preset,
        "-crf",
        str(args.crf),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output),
    ]


def split_video(video_path: Path, output_dir: Path, args: argparse.Namespace) -> int:
    duration = ffprobe_duration(video_path)
    segment_count = max(1, math.ceil(duration / args.segment_seconds))
    srt_path = find_matching_srt(video_path)
    cues = parse_srt(srt_path) if srt_path else []

    print(
        f"{video_path.name}: duration={duration:.3f}s "
        f"segments={segment_count} srt={'yes' if srt_path else 'no'}"
    )

    made = 0
    for index in range(segment_count):
        start_seconds = index * args.segment_seconds
        end_seconds = min((index + 1) * args.segment_seconds, duration)
        segment_duration = max(0.001, end_seconds - start_seconds)
        stem = f"{video_path.stem}_seg{index + 1:03d}"
        out_video = output_dir / f"{stem}{video_path.suffix}"
        out_srt = output_dir / f"{stem}.SRT"

        if not args.overwrite and out_video.exists() and (not srt_path or out_srt.exists()):
            print(f"  skip {stem}: output exists")
            continue

        if not args.dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)

        cmd = build_ffmpeg_cmd(
            video_path, out_video, start_seconds, segment_duration, args
        )
        run(cmd, args.dry_run)

        cue_count = 0
        if srt_path:
            cue_count = write_segment_srt(
                cues,
                out_srt,
                int(round(start_seconds * 1000)),
                int(round(end_seconds * 1000)),
                args.dry_run,
            )

        print(
            f"  {stem}: {start_seconds:.3f}-{end_seconds:.3f}s"
            + (f" cues={cue_count}" if srt_path else "")
        )
        made += 1

    return made


def main() -> int:
    args = parse_args()
    if args.segment_seconds <= 0:
        print("--segment-seconds must be greater than 0", file=sys.stderr)
        return 2

    input_dir = args.input_dir
    output_dir = args.output_dir or input_dir / "seg"

    if not input_dir.exists():
        print(f"Input directory does not exist: {input_dir}", file=sys.stderr)
        return 2

    require_command("ffmpeg")
    require_command("ffprobe")

    videos = iter_videos(input_dir, output_dir, args.video_ext)
    if not videos:
        print(f"No videos found in {input_dir}")
        return 0

    total = 0
    for video_path in videos:
        total += split_video(video_path, output_dir, args)

    print(f"Done. Created/updated {total} segment(s) in {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
