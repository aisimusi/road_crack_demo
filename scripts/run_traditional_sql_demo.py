#!/usr/bin/env python3
from __future__ import annotations

import argparse
import codecs
import os
import pty
import select
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "backend" / "road_crack_demo.db"


DEMO_COMMANDS = [
    """.headers on
""",
    """.mode column
""",
    """.timer on
""",
    """.tables
""",
    """SELECT COUNT(*) AS crack_count FROM crack_record;
""",
    """SELECT
  MIN(detected_at) AS min_detected_at,
  MAX(detected_at) AS max_detected_at
FROM crack_record;
""",
    """SELECT
  severity_level,
  severity_label,
  COUNT(*) AS count
FROM crack_record
GROUP BY severity_level, severity_label
ORDER BY severity_level;
""",
    """DROP TABLE IF EXISTS tmp_query_params;
CREATE TEMP TABLE tmp_query_params AS
SELECT
  '江苏大学' AS place_name,
  119.5144 AS center_lng,
  32.1979 AS center_lat,
  500.0 AS radius_m,
  '2026-05-01' AS start_date,
  '2026-07-02' AS end_exclusive_date,
  2 AS severity_min,
  5 AS top_n;

SELECT * FROM tmp_query_params;
""",
    """DROP TABLE IF EXISTS tmp_latest_recent_record;
CREATE TEMP TABLE tmp_latest_recent_record AS
WITH r AS (
  SELECT
    cr.*,
    ROW_NUMBER() OVER (
      PARTITION BY cr.identity_id
      ORDER BY cr.detected_at DESC, cr.id DESC
    ) AS rn
  FROM crack_record cr
  CROSS JOIN tmp_query_params p
  WHERE cr.identity_id IS NOT NULL
    AND cr.detected_at >= p.start_date
    AND cr.detected_at < p.end_exclusive_date
    AND cr.severity_level >= p.severity_min
)
SELECT *
FROM r
WHERE rn = 1;

SELECT COUNT(*) AS latest_recent_count FROM tmp_latest_recent_record;
""",
    """DROP TABLE IF EXISTS tmp_spatial_candidates;
CREATE TEMP TABLE tmp_spatial_candidates AS
WITH c AS (
  SELECT
    ci.id AS identity_id,
    ci.identity_code,
    ci.priority_level,
    ci.lifecycle_status,
    ci.maintenance_status,
    ci.observation_count,
    ci.last_seen_at,
    rr.id AS latest_record_id,
    rr.crack_code,
    rr.task_id,
    rr.frame_id,
    rr.road_name,
    rr.district,
    rr.crack_type,
    rr.severity_level,
    rr.severity_label,
    rr.severity_score,
    rr.length_m,
    rr.avg_width_cm,
    rr.max_width_cm,
    rr.area_m2,
    rr.longitude,
    rr.latitude,
    rr.original_image_uri,
    rr.result_image_uri,
    rr.detected_at,
    sqrt(
      pow((rr.longitude - p.center_lng) * 111320.0 * cos(radians((rr.latitude + p.center_lat) / 2.0)), 2) +
      pow((rr.latitude - p.center_lat) * 111320.0, 2)
    ) AS distance_m
  FROM crack_identity ci
  JOIN tmp_latest_recent_record rr ON rr.identity_id = ci.id
  CROSS JOIN tmp_query_params p
  WHERE ci.priority_level = '高'
    AND ci.lifecycle_status = 'active'
    AND ci.maintenance_status NOT IN ('closed','completed','complete','finished','done','repaired','resolved','已闭环','已完成','已修复')
)
SELECT *
FROM c
WHERE distance_m <= (SELECT radius_m FROM tmp_query_params);

SELECT COUNT(*) AS spatial_candidate_count FROM tmp_spatial_candidates;
""",
    """DROP TABLE IF EXISTS tmp_ranked_cracks;
CREATE TEMP TABLE tmp_ranked_cracks AS
SELECT
  *,
  CASE priority_level WHEN '高' THEN 3 WHEN '中' THEN 2 WHEN '低' THEN 1 ELSE 0 END AS priority_rank,
  round(
    severity_level * 30.0 +
    min(area_m2 * 120.0, 25.0) +
    min(length_m * 2.0, 20.0) +
    min(max_width_cm * 10.0, 20.0) +
    severity_score * 10.0,
    1
  ) AS sql_risk_score,
  CASE
    WHEN severity_level >= 3 OR max_width_cm * 10.0 >= 5.0
      THEN '立即现场复核；优先封缝/灌缝，宽缝或面积较大处做局部铣刨修补，并在修复后复检。'
    WHEN severity_level = 2
      THEN '纳入近期养护计划；先做清缝、灌缝或贴缝，持续跟踪长度和面积变化。'
    ELSE '保持观察，结合常规巡检做预防性养护。'
  END AS treatment_advice
FROM tmp_spatial_candidates;
""",
    """DROP TABLE IF EXISTS tmp_top5_cracks;
CREATE TEMP TABLE tmp_top5_cracks AS
SELECT
  ROW_NUMBER() OVER (
    ORDER BY priority_rank DESC, severity_level DESC, area_m2 DESC,
             length_m DESC, max_width_cm DESC, distance_m ASC, detected_at DESC
  ) AS rank_no,
  *
FROM tmp_ranked_cracks
ORDER BY priority_rank DESC, severity_level DESC, area_m2 DESC,
         length_m DESC, max_width_cm DESC, distance_m ASC, detected_at DESC
LIMIT 5;
""",
    """SELECT
  rank_no,
  identity_code,
  crack_code,
  road_name,
  district,
  round(distance_m, 1) AS distance_m,
  priority_level,
  severity_label,
  sql_risk_score,
  round(length_m, 2) AS length_m,
  round(max_width_cm * 10.0, 1) AS max_width_mm,
  round(area_m2, 4) AS area_m2,
  longitude,
  latitude,
  detected_at,
  result_image_uri AS evidence_overlay_image,
  treatment_advice
FROM tmp_top5_cracks
ORDER BY rank_no;
""",
]


def _quote_command(command: str) -> str:
    return shlex.quote(command)


def open_terminal(extra_args: list[str]) -> int:
    script_path = Path(__file__).resolve()
    player_args = " ".join(shlex.quote(arg) for arg in [*extra_args, "--player"])
    command = (
        f"cd {_quote_command(str(PROJECT_ROOT))}; "
        f"{_quote_command(sys.executable)} {_quote_command(str(script_path))} {player_args}; "
        "echo; read -r -p '窗口已保留，按 Enter 关闭...'"
    )

    if os.name == "nt":
        subprocess.Popen(
            ["cmd", "/k", sys.executable, str(script_path), *extra_args, "--player"],
            cwd=str(PROJECT_ROOT),
        )
        return 0

    terminal_commands = [
        ("gnome-terminal", ["gnome-terminal", "--", "bash", "-lc", command]),
        ("konsole", ["konsole", "-e", "bash", "-lc", command]),
        ("xfce4-terminal", ["xfce4-terminal", "--command", f"bash -lc {shlex.quote(command)}"]),
        ("xterm", ["xterm", "-e", "bash", "-lc", command]),
    ]
    for binary, argv in terminal_commands:
        if shutil.which(binary):
            subprocess.Popen(argv, cwd=str(PROJECT_ROOT))
            return 0

    print("未找到可自动打开的终端程序，改为在当前窗口运行。", file=sys.stderr)
    return run_player(parse_player_args([*extra_args, "--player"]))


def parse_player_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="逐字输入传统 SQLite 查询演示脚本。")
    parser.add_argument("--player", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--delay", type=float, default=0.018, help="每个字符之间的等待秒数，默认 0.018。")
    parser.add_argument("--line-delay", type=float, default=0.12, help="每行之后的额外等待秒数，默认 0.12。")
    parser.add_argument("--command-delay", type=float, default=1.0, help="每段 SQL 执行后的等待秒数，默认 1.0。")
    parser.add_argument("--no-pause", action="store_true", help="最终结果输出后不等待，直接退出。")
    return parser.parse_args(argv)


def reader_loop(master_fd: int, stop_event: threading.Event) -> None:
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    while not stop_event.is_set():
        ready, _, _ = select.select([master_fd], [], [], 0.05)
        if not ready:
            continue
        try:
            data = os.read(master_fd, 4096)
        except OSError:
            break
        if not data:
            break
        text = decoder.decode(data)
        sys.stdout.write(text)
        sys.stdout.flush()


def type_text(master_fd: int, text: str, *, delay: float, line_delay: float) -> None:
    for char in text:
        os.write(master_fd, char.encode("utf-8"))
        if delay > 0:
            time.sleep(delay)
        if char == "\n" and line_delay > 0:
            time.sleep(line_delay)
    if not text.endswith("\n"):
        os.write(master_fd, b"\n")


def run_player(args: argparse.Namespace) -> int:
    if not DB_PATH.exists():
        print(f"数据库不存在：{DB_PATH}", file=sys.stderr)
        return 1

    sqlite_bin = shutil.which("sqlite3")
    if not sqlite_bin:
        print("未找到 sqlite3，请先安装或激活包含 sqlite3 的 Anaconda 环境。", file=sys.stderr)
        return 1

    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        [sqlite_bin, str(DB_PATH)],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=str(PROJECT_ROOT),
        close_fds=True,
    )
    os.close(slave_fd)

    stop_event = threading.Event()
    reader = threading.Thread(target=reader_loop, args=(master_fd, stop_event), daemon=True)
    reader.start()

    try:
        time.sleep(0.8)
        for command in DEMO_COMMANDS:
            type_text(master_fd, command, delay=args.delay, line_delay=args.line_delay)
            time.sleep(args.command_delay)

        time.sleep(1.0)
        if not args.no_pause:
            print("\n\n演示已运行到最终结果。按 Enter 退出 sqlite 并保留窗口。")
            input()
        os.write(master_fd, b".quit\n")
        time.sleep(0.2)
    finally:
        stop_event.set()
        try:
            process.terminate()
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.kill()
        except OSError:
            pass
        try:
            os.close(master_fd)
        except OSError:
            pass

    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_player_args(argv or sys.argv[1:])
    if args.player:
        return run_player(args)

    extra_args: list[str] = []
    for flag, value in (
        ("--delay", args.delay),
        ("--line-delay", args.line_delay),
        ("--command-delay", args.command_delay),
    ):
        extra_args.extend([flag, str(value)])
    if args.no_pause:
        extra_args.append("--no-pause")
    return open_terminal(extra_args)


if __name__ == "__main__":
    raise SystemExit(main())
