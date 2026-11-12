from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class SrtEntry:
    index: int
    start_seconds: float
    end_seconds: float
    captured_at: datetime | None
    latitude: float | None
    longitude: float | None
    rel_alt: float | None
    abs_alt: float | None
    focal_len: float | None
    dzoom_ratio: float | None
    frame_count: int | None
    yaw: float | None
    pitch: float | None
    roll: float | None


@dataclass(frozen=True)
class SrtCoordinateSummary:
    center_longitude: float
    center_latitude: float
    start_longitude: float
    start_latitude: float
    end_longitude: float
    end_latitude: float
    coordinate_count: int


def _parse_srt_time(value: str) -> float:
    match = re.match(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", value.strip())
    if not match:
        raise ValueError(f"无法解析 SRT 时间: {value}")
    hours, minutes, seconds, millis = (int(part) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def _extract_float(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text)
    return float(match.group(1)) if match else None


def _extract_int(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else None


def parse_srt_file(path: Path) -> list[SrtEntry]:
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    blocks = re.split(r"\n\s*\n", text.strip())
    entries: list[SrtEntry] = []

    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2 or "-->" not in lines[1]:
            continue

        index = int(lines[0]) if lines[0].isdigit() else len(entries) + 1
        start_raw, end_raw = [part.strip() for part in lines[1].split("-->", 1)]
        payload = " ".join(lines[2:])
        captured_at = None
        datetime_match = re.search(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)", payload)
        if datetime_match:
            captured_at = datetime.strptime(datetime_match.group(1), "%Y-%m-%d %H:%M:%S.%f")

        entries.append(
            SrtEntry(
                index=index,
                start_seconds=_parse_srt_time(start_raw),
                end_seconds=_parse_srt_time(end_raw),
                captured_at=captured_at,
                latitude=_extract_float(r"\[latitude:\s*([-+]?\d+(?:\.\d+)?)\]", payload),
                longitude=_extract_float(r"\[longitude:\s*([-+]?\d+(?:\.\d+)?)\]", payload),
                rel_alt=_extract_float(r"\[rel_alt:\s*([-+]?\d+(?:\.\d+)?)", payload),
                abs_alt=_extract_float(r"abs_alt:\s*([-+]?\d+(?:\.\d+)?)\]", payload),
                focal_len=_extract_float(r"\[focal_len:\s*([-+]?\d+(?:\.\d+)?)\]", payload),
                dzoom_ratio=_extract_float(r"\[dzoom_ratio:\s*([-+]?\d+(?:\.\d+)?)\]", payload),
                frame_count=_extract_int(r"FrameCnt:\s*(\d+)", payload),
                yaw=_extract_float(r"\[gb_yaw:\s*([-+]?\d+(?:\.\d+)?)", payload),
                pitch=_extract_float(r"gb_pitch:\s*([-+]?\d+(?:\.\d+)?)", payload),
                roll=_extract_float(r"gb_roll:\s*([-+]?\d+(?:\.\d+)?)\]", payload),
            )
        )

    if not entries:
        raise ValueError(f"SRT 文件没有可解析的 DJI 元数据: {path.name}")
    return entries


def summarize_srt_coordinates(entries: list[SrtEntry]) -> SrtCoordinateSummary:
    coordinates: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for entry in entries:
        longitude = entry.longitude
        latitude = entry.latitude
        if longitude is None or latitude is None:
            continue
        if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
            continue
        key = (round(float(longitude), 7), round(float(latitude), 7))
        if key in seen:
            continue
        seen.add(key)
        coordinates.append((float(longitude), float(latitude)))

    if not coordinates:
        raise ValueError("SRT 文件缺少有效经纬度，无法自动获取道路和区域")

    longitudes = [item[0] for item in coordinates]
    latitudes = [item[1] for item in coordinates]
    start_longitude, start_latitude = coordinates[0]
    end_longitude, end_latitude = coordinates[-1]
    return SrtCoordinateSummary(
        center_longitude=sum(longitudes) / len(longitudes),
        center_latitude=sum(latitudes) / len(latitudes),
        start_longitude=start_longitude,
        start_latitude=start_latitude,
        end_longitude=end_longitude,
        end_latitude=end_latitude,
        coordinate_count=len(coordinates),
    )
