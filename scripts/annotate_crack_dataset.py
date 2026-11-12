#!/usr/bin/env python3
"""Local browser tool for building a crack segmentation dataset from DJI videos."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import socket
import sys
import threading
import webbrowser
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import cv2
    import numpy as np
except ImportError as exc:  # pragma: no cover - depends on the selected conda env
    raise SystemExit(
        "需要 OpenCV 和 NumPy。请先执行 conda activate roadcrack（或 crackmamba）。"
    ) from exc


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = PROJECT_ROOT / "annotation_tool"
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}
QUADRANTS = ("tl", "tr", "bl", "br")
QUADRANT_NAMES = {"tl": "左上", "tr": "右上", "bl": "左下", "br": "右下"}
VALID_STATUSES = {"pending", "annotated", "negative", "skipped"}


@dataclass(frozen=True)
class VideoInfo:
    path: str
    name: str
    stem: str
    fps: float
    frame_count: int
    width: int
    height: int


@dataclass(frozen=True)
class Candidate:
    id: str
    video_path: str
    video_name: str
    segment: str
    frame_index: int
    time_seconds: float
    sample_number: int
    quadrant: str
    quadrant_name: str
    width: int
    height: int


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从 DJI 分段视频中分层抽帧，并在浏览器中标注裂缝分割掩膜。"
    )
    parser.add_argument(
        "--video-dir", type=Path, default=PROJECT_ROOT / "dji_videos" / "seg"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=PROJECT_ROOT / "annotations" / "road_crack"
    )
    parser.add_argument(
        "--frames-per-video",
        type=int,
        default=3,
        help="每个视频片段均匀抽取的帧数，默认 3。每帧产生 4 个待标图块。",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="监听地址，默认 0.0.0.0，允许同一局域网内的设备访问。",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器。")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="重建尚未开始标注的数据清单；已有标注时会拒绝执行。",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="只打印采样统计，不启动服务。"
    )
    return parser.parse_args()


def safe_case_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    return cleaned or "video"


def discover_lan_ipv4_addresses() -> list[str]:
    """Return usable IPv4 addresses without relying on platform-specific commands."""
    addresses: set[str] = set()
    try:
        _, _, hostname_addresses = socket.gethostbyname_ex(socket.gethostname())
        addresses.update(hostname_addresses)
    except OSError:
        pass

    # A UDP connect selects the host's route without sending application data.
    for target in ("10.255.255.255", "8.8.8.8"):
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect((target, 80))
            addresses.add(probe.getsockname()[0])
        except OSError:
            pass
        finally:
            probe.close()

    return sorted(
        address
        for address in addresses
        if address and not address.startswith("127.") and address != "0.0.0.0"
    )


def access_urls(host: str, port: int) -> tuple[str, list[str]]:
    if host in {"0.0.0.0", "::"}:
        local_url = f"http://127.0.0.1:{port}"
        lan_urls = [f"http://{address}:{port}" for address in discover_lan_ipv4_addresses()]
        return local_url, lan_urls
    return f"http://{host}:{port}", []


def inspect_video(path: Path) -> VideoInfo:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"无法打开视频：{path}")
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    finally:
        capture.release()
    if fps <= 0 or frame_count <= 0 or width < 2 or height < 2:
        raise RuntimeError(f"视频元数据不完整：{path}")
    return VideoInfo(
        path=str(path.resolve()),
        name=path.name,
        stem=path.stem,
        fps=round(fps, 6),
        frame_count=frame_count,
        width=width,
        height=height,
    )


def discover_videos(video_dir: Path) -> list[VideoInfo]:
    if not video_dir.is_dir():
        raise FileNotFoundError(f"视频目录不存在：{video_dir}")
    paths = sorted(
        (
            path
            for path in video_dir.iterdir()
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
        ),
        key=lambda path: path.name.lower(),
    )
    if not paths:
        raise FileNotFoundError(f"目录中没有视频：{video_dir}")
    return [inspect_video(path) for path in paths]


def sampled_frame_indices(frame_count: int, count: int) -> list[int]:
    """Choose interior, evenly spaced frames without duplicate indices."""
    if count <= 0:
        raise ValueError("--frames-per-video 必须大于 0")
    if frame_count <= 0:
        return []
    indices: list[int] = []
    for index in range(count):
        frame_index = round((index + 1) * (frame_count - 1) / (count + 1))
        if frame_index not in indices:
            indices.append(frame_index)
    return indices


def quadrant_bounds(width: int, height: int, quadrant: str) -> tuple[int, int, int, int]:
    if quadrant not in QUADRANTS:
        raise ValueError(f"未知象限：{quadrant}")
    mid_x, mid_y = width // 2, height // 2
    x0, x1 = (0, mid_x) if quadrant.endswith("l") else (mid_x, width)
    y0, y1 = (0, mid_y) if quadrant.startswith("t") else (mid_y, height)
    return x0, y0, x1, y1


def build_candidates(videos: list[VideoInfo], frames_per_video: int) -> list[Candidate]:
    """Round-robin by segment so adjacent candidates represent different roads."""
    frames = {video.path: sampled_frame_indices(video.frame_count, frames_per_video) for video in videos}
    candidates: list[Candidate] = []
    for quadrant in QUADRANTS:
        for sample_offset in range(frames_per_video):
            for video in videos:
                video_frames = frames[video.path]
                if sample_offset >= len(video_frames):
                    continue
                frame_index = video_frames[sample_offset]
                x0, y0, x1, y1 = quadrant_bounds(video.width, video.height, quadrant)
                case_id = (
                    f"{safe_case_part(video.stem)}_f{frame_index:06d}_{quadrant}"
                )
                candidates.append(
                    Candidate(
                        id=case_id,
                        video_path=video.path,
                        video_name=video.name,
                        segment=video.stem,
                        frame_index=frame_index,
                        time_seconds=round(frame_index / video.fps, 3),
                        sample_number=sample_offset + 1,
                        quadrant=quadrant,
                        quadrant_name=QUADRANT_NAMES[quadrant],
                        width=x1 - x0,
                        height=y1 - y0,
                    )
                )
    return candidates


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def decode_mask(data_url: str, width: int, height: int) -> np.ndarray:
    if not data_url.startswith("data:image/png;base64,"):
        raise ValueError("掩膜必须是 PNG data URL")
    try:
        raw = base64.b64decode(data_url.split(",", 1)[1], validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("掩膜 Base64 数据无效") from exc
    encoded = np.frombuffer(raw, dtype=np.uint8)
    mask = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
    if mask is None:
        raise ValueError("无法解析掩膜 PNG")
    if mask.ndim == 3:
        if mask.shape[2] == 4:
            alpha = mask[:, :, 3]
            mask = cv2.cvtColor(mask[:, :, :3], cv2.COLOR_BGR2GRAY)
            mask = np.where(alpha > 0, mask, 0).astype(np.uint8)
        else:
            mask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
    if mask.shape != (height, width):
        raise ValueError(
            f"掩膜尺寸应为 {width}x{height}，实际为 {mask.shape[1]}x{mask.shape[0]}"
        )
    return (mask > 0).astype(np.uint8)


class AnnotationStore:
    def __init__(
        self,
        video_dir: Path,
        output_dir: Path,
        frames_per_video: int,
        rebuild: bool = False,
    ) -> None:
        self.video_dir = video_dir.resolve()
        self.output_dir = output_dir.resolve()
        self.images_dir = self.output_dir / "imagesTr"
        self.labels_dir = self.output_dir / "labelsTr"
        self.manifest_path = self.output_dir / "annotation_manifest.json"
        self.dataset_path = self.output_dir / "dataset.json"
        self._lock = threading.RLock()
        self.videos = discover_videos(self.video_dir)

        existing = self._read_manifest()
        if rebuild and existing and self._completed_count(existing) > 0:
            raise RuntimeError("已有标注，不能使用 --rebuild。请换一个 --output-dir。")
        if existing and not rebuild:
            self.manifest = existing
            self._validate_existing_sources()
        else:
            candidates = build_candidates(self.videos, frames_per_video)
            created_at = now_iso()
            self.manifest = {
                "schema_version": 1,
                "created_at": created_at,
                "updated_at": created_at,
                "video_dir": str(self.video_dir),
                "output_dir": str(self.output_dir),
                "frames_per_video": frames_per_video,
                "videos": [asdict(video) for video in self.videos],
                "candidates": [
                    {**asdict(candidate), "status": "pending", "updated_at": None}
                    for candidate in candidates
                ],
            }
            self._write_manifest()
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.labels_dir.mkdir(parents=True, exist_ok=True)
        self._write_dataset_json()

    def _read_manifest(self) -> dict[str, Any] | None:
        if not self.manifest_path.exists():
            return None
        payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1 or not isinstance(payload.get("candidates"), list):
            raise RuntimeError(f"不支持的标注清单：{self.manifest_path}")
        return payload

    @staticmethod
    def _completed_count(manifest: dict[str, Any]) -> int:
        return sum(
            item.get("status") in {"annotated", "negative"}
            for item in manifest.get("candidates", [])
        )

    def _validate_existing_sources(self) -> None:
        missing = sorted(
            {
                item["video_path"]
                for item in self.manifest["candidates"]
                if not Path(item["video_path"]).exists()
            }
        )
        if missing:
            raise RuntimeError("清单中的源视频不存在：" + "、".join(missing[:3]))

    def _write_manifest(self) -> None:
        self.manifest["updated_at"] = now_iso()
        atomic_write_json(self.manifest_path, self.manifest)

    def _write_dataset_json(self) -> None:
        payload = {
            "channel_names": {"0": "R", "1": "G", "2": "B"},
            "labels": {"background": 0, "crack": 1},
            "numTraining": self._completed_count(self.manifest),
            "file_ending": ".png",
            "name": (
                "DJIRoadCrackWeakAdaptation"
                if self.manifest.get("annotation_set") == "weak_road_adaptation"
                else "DJIRoadCrack"
            ),
            "overwrite_image_reader_writer": "NaturalImage2DIO",
        }
        atomic_write_json(self.dataset_path, payload)

    def _candidate(self, index: int) -> dict[str, Any]:
        candidates = self.manifest["candidates"]
        if index < 0 or index >= len(candidates):
            raise IndexError("样本编号超出范围")
        return candidates[index]

    @staticmethod
    @lru_cache(maxsize=8)
    def _read_frame(video_path: str, frame_index: int) -> np.ndarray:
        capture = cv2.VideoCapture(video_path)
        if not capture.isOpened():
            raise RuntimeError(f"无法打开视频：{video_path}")
        try:
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
        finally:
            capture.release()
        if not ok or frame is None:
            raise RuntimeError(f"无法读取第 {frame_index} 帧：{video_path}")
        return frame

    def tile(self, index: int) -> np.ndarray:
        item = self._candidate(index)
        frame = self._read_frame(item["video_path"], item["frame_index"])
        x0, y0, x1, y1 = quadrant_bounds(
            frame.shape[1], frame.shape[0], item["quadrant"]
        )
        return frame[y0:y1, x0:x1].copy()

    def context_frame(self, index: int) -> np.ndarray:
        item = self._candidate(index)
        frame = self._read_frame(item["video_path"], item["frame_index"]).copy()
        height, width = frame.shape[:2]
        x0, y0, x1, y1 = quadrant_bounds(width, height, item["quadrant"])
        overlay = frame.copy()
        cv2.rectangle(overlay, (x0, y0), (x1 - 1, y1 - 1), (30, 190, 255), -1)
        frame = cv2.addWeighted(overlay, 0.2, frame, 0.8, 0)
        cv2.line(frame, (width // 2, 0), (width // 2, height), (255, 255, 255), 2)
        cv2.line(frame, (0, height // 2), (width, height // 2), (255, 255, 255), 2)
        cv2.rectangle(frame, (x0, y0), (x1 - 1, y1 - 1), (30, 190, 255), 4)
        return frame

    @staticmethod
    def encode_png(image: np.ndarray) -> bytes:
        ok, encoded = cv2.imencode(".png", image)
        if not ok:
            raise RuntimeError("PNG 编码失败")
        return encoded.tobytes()

    @staticmethod
    def encode_jpeg(image: np.ndarray, max_width: int | None = None) -> bytes:
        if max_width and image.shape[1] > max_width:
            scale = max_width / image.shape[1]
            image = cv2.resize(
                image, (max_width, round(image.shape[0] * scale)), interpolation=cv2.INTER_AREA
            )
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise RuntimeError("JPEG 编码失败")
        return encoded.tobytes()

    def mask_png(self, index: int) -> bytes:
        item = self._candidate(index)
        path = self.labels_dir / f"{item['id']}.png"
        if path.exists():
            mask = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if mask is None:
                raise RuntimeError(f"无法读取掩膜：{path}")
            return self.encode_png((mask > 0).astype(np.uint8) * 255)
        return self.encode_png(np.zeros((item["height"], item["width"]), np.uint8))

    def save_annotation(self, index: int, mask_data_url: str, negative: bool) -> None:
        with self._lock:
            item = self._candidate(index)
            mask = decode_mask(mask_data_url, item["width"], item["height"])
            if negative:
                mask.fill(0)
            elif not np.any(mask):
                raise ValueError("掩膜为空；无裂缝图块请使用“标为空白”。")
            tile = self.tile(index)
            if tile.shape[:2] != mask.shape:
                raise RuntimeError("图块与掩膜尺寸不一致")
            image_path = self.images_dir / f"{item['id']}_0000.png"
            label_path = self.labels_dir / f"{item['id']}.png"
            if not cv2.imwrite(str(image_path), tile):
                raise RuntimeError(f"写入图像失败：{image_path}")
            if not cv2.imwrite(str(label_path), mask):
                raise RuntimeError(f"写入掩膜失败：{label_path}")
            item["status"] = "negative" if negative else "annotated"
            item["updated_at"] = now_iso()
            item["crack_pixels"] = int(mask.sum())
            item["image_path"] = str(image_path)
            item["label_path"] = str(label_path)
            self._write_manifest()
            self._write_dataset_json()

    def set_status(self, index: int, status: str) -> None:
        if status not in {"pending", "skipped"}:
            raise ValueError("这里只能设置 pending 或 skipped")
        with self._lock:
            item = self._candidate(index)
            item["status"] = status
            item["updated_at"] = now_iso()
            self._write_manifest()
            self._write_dataset_json()

    def public_state(self) -> dict[str, Any]:
        candidates = self.manifest["candidates"]
        counts = {status: 0 for status in VALID_STATUSES}
        segments: dict[str, dict[str, Any]] = {}
        split_counts: dict[str, int] = {}
        for item in candidates:
            status = item.get("status", "pending")
            counts[status] = counts.get(status, 0) + 1
            split = item.get("dataset_split")
            if split:
                split_counts[split] = split_counts.get(split, 0) + 1
            segment = segments.setdefault(
                item["segment"], {"name": item["segment"], "total": 0, "completed": 0}
            )
            segment["total"] += 1
            segment["completed"] += status in {"annotated", "negative"}
        return {
            "schema_version": self.manifest["schema_version"],
            "counts": counts,
            "total": len(candidates),
            "output_dir": str(self.output_dir),
            "annotation_set": self.manifest.get("annotation_set", "road_crack"),
            "annotation_title": self.manifest.get("annotation_title", "道路裂缝标注"),
            "split_counts": split_counts,
            "segments": list(segments.values()),
            "candidates": [
                {
                    key: item.get(key)
                    for key in (
                        "id",
                        "video_name",
                        "segment",
                        "frame_index",
                        "time_seconds",
                        "sample_number",
                        "quadrant",
                        "quadrant_name",
                        "width",
                        "height",
                        "status",
                        "crack_pixels",
                        "dataset_split",
                        "split_name",
                        "annotation_set",
                    )
                }
                for item in candidates
            ],
        }


class AnnotationHandler(BaseHTTPRequestHandler):
    store: AnnotationStore
    server_version = "RoadCrackAnnotation/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: Any, status: int = 200) -> None:
        self._send(
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            status,
        )

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    def _candidate_route(self, path: str, suffix: str) -> int | None:
        match = re.fullmatch(rf"/api/candidates/(\d+)/{suffix}", path)
        return int(match.group(1)) if match else None

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/state":
                self._json(self.store.public_state())
                return
            index = self._candidate_route(path, "image")
            if index is not None:
                self._send(self.store.encode_jpeg(self.store.tile(index)), "image/jpeg")
                return
            index = self._candidate_route(path, "context")
            if index is not None:
                self._send(
                    self.store.encode_jpeg(self.store.context_frame(index), max_width=640),
                    "image/jpeg",
                )
                return
            index = self._candidate_route(path, "mask")
            if index is not None:
                self._send(self.store.mask_png(index), "image/png")
                return
            static_files = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8"),
            }
            if path in static_files:
                filename, content_type = static_files[path]
                self._send((STATIC_DIR / filename).read_bytes(), content_type)
                return
            self._error(HTTPStatus.NOT_FOUND, "页面不存在")
        except IndexError as exc:
            self._error(HTTPStatus.NOT_FOUND, str(exc))
        except Exception as exc:  # pragma: no cover - request boundary
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 12 * 1024 * 1024:
                raise ValueError("请求体为空或过大")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            index = self._candidate_route(path, "save")
            if index is not None:
                self.store.save_annotation(
                    index,
                    str(payload.get("mask", "")),
                    bool(payload.get("negative", False)),
                )
                self._json(self.store.public_state())
                return
            index = self._candidate_route(path, "status")
            if index is not None:
                self.store.set_status(index, str(payload.get("status", "")))
                self._json(self.store.public_state())
                return
            self._error(HTTPStatus.NOT_FOUND, "接口不存在")
        except (ValueError, json.JSONDecodeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except IndexError as exc:
            self._error(HTTPStatus.NOT_FOUND, str(exc))
        except Exception as exc:  # pragma: no cover - request boundary
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))


def main() -> None:
    args = parse_args()
    if args.frames_per_video <= 0:
        raise SystemExit("--frames-per-video 必须大于 0")
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port 必须在 1 到 65535 之间")
    store = AnnotationStore(
        args.video_dir, args.output_dir, args.frames_per_video, rebuild=args.rebuild
    )
    state = store.public_state()
    print(
        f"找到 {len(store.videos)} 个视频片段，生成 {state['total']} 个待标图块；"
        f"已完成 {state['counts']['annotated'] + state['counts']['negative']} 个。"
    )
    print(f"输出目录：{store.output_dir}")
    if args.dry_run:
        return
    AnnotationHandler.store = store
    try:
        server = ThreadingHTTPServer((args.host, args.port), AnnotationHandler)
    except OSError as exc:
        raise SystemExit(f"无法监听 {args.host}:{args.port}：{exc}") from exc
    local_url, lan_urls = access_urls(args.host, args.port)
    print(f"本机访问：{local_url}")
    for lan_url in lan_urls:
        print(f"局域网访问：{lan_url}")
    if args.host in {"0.0.0.0", "::"} and not lan_urls:
        print("未自动识别到局域网 IPv4 地址，请用本机实际 IP 加端口访问。")
    print("按 Ctrl+C 停止服务，标注结果会在每次保存后立即落盘。")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(local_url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n标注工具已停止。")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
