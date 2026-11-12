from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agent.sql_guard import ensure_select_sql

KNOWN_ROAD_NAMES = ("中山路", "学府路", "解放路")


@dataclass
class QueryPlan:
    sql: str
    params: dict[str, Any]
    summary_builder: Callable[[list[dict[str, Any]]], str]


def validate_select_sql(sql: str) -> bool:
    try:
        ensure_select_sql(sql, require_limit=False)
    except PermissionError:
        return False
    return True


def extract_road_name(question: str) -> str | None:
    for road_name in KNOWN_ROAD_NAMES:
        if road_name in question:
            return road_name

    match = re.search(r"([\u4e00-\u9fa5]{2,8}路)", question)
    return match.group(1) if match else None


def build_query_plan(question: str) -> QueryPlan:
    normalized = question.strip().replace("？", "?").replace("。", "")
    road_name = extract_road_name(normalized)

    if road_name and ("道路情况" in normalized or "路况" in normalized):
        sql = """
        SELECT crack_code, road_name, severity_label, crack_type, length_m, avg_width_cm, detected_at
        FROM crack_record
        WHERE road_name = :road_name
        ORDER BY detected_at DESC, severity_level DESC
        LIMIT 20
        """

        def summarize(rows: list[dict[str, Any]]) -> str:
            if not rows:
                return f"{road_name} 当前还没有裂缝检测记录。"
            severe = sum(1 for row in rows if row["severity_label"] == "严重")
            return f"{road_name} 共返回 {len(rows)} 条裂缝记录，其中严重裂缝 {severe} 条。"

        return QueryPlan(sql=sql, params={"road_name": road_name}, summary_builder=summarize)

    if "严重" in normalized and "裂缝" in normalized:
        sql = """
        SELECT crack_code, road_name, severity_label, crack_type, length_m, avg_width_cm, detected_at
        FROM crack_record
        WHERE severity_level = 3
        ORDER BY detected_at DESC, severity_score DESC
        LIMIT 20
        """

        def summarize(rows: list[dict[str, Any]]) -> str:
            if not rows:
                return "当前没有严重裂缝记录。"
            roads = sorted({row["road_name"] for row in rows})
            return f"当前共查询到 {len(rows)} 条严重裂缝，涉及道路：{'、'.join(roads)}。"

        return QueryPlan(sql=sql, params={}, summary_builder=summarize)

    if "最近一次" in normalized and ("多少裂缝" in normalized or "发现了多少" in normalized):
        sql = """
        SELECT t.id AS task_id, t.task_name, t.road_name, COUNT(c.id) AS crack_count, MAX(c.detected_at) AS latest_detected_at
        FROM inspection_task t
        LEFT JOIN crack_record c ON c.task_id = t.id
        WHERE t.id = (
            SELECT id
            FROM inspection_task
            ORDER BY COALESCE(finished_at, created_at) DESC
            LIMIT 1
        )
        GROUP BY t.id, t.task_name, t.road_name
        """

        def summarize(rows: list[dict[str, Any]]) -> str:
            if not rows:
                return "当前还没有巡检任务记录。"
            row = rows[0]
            return f"最近一次巡检任务为 {row['task_name']}，道路为 {row['road_name']}，共发现 {row['crack_count']} 条裂缝。"

        return QueryPlan(sql=sql, params={}, summary_builder=summarize)

    if "裂缝最多" in normalized and "哪条路" in normalized:
        sql = """
        SELECT road_name, COUNT(id) AS crack_count
        FROM crack_record
        GROUP BY road_name
        ORDER BY crack_count DESC, road_name ASC
        LIMIT 1
        """

        def summarize(rows: list[dict[str, Any]]) -> str:
            if not rows:
                return "当前没有裂缝数据，无法判断哪条路裂缝最多。"
            row = rows[0]
            return f"目前裂缝最多的是 {row['road_name']}，共记录 {row['crack_count']} 条裂缝。"

        return QueryPlan(sql=sql, params={}, summary_builder=summarize)

    raise ValueError("暂不支持该问题，请尝试道路情况、严重裂缝、最近一次巡检或裂缝最多的道路这几类问法。")


def run_text_query(db: Session, question: str) -> dict[str, Any]:
    plan = build_query_plan(question)
    sql = re.sub(r"\s+", " ", plan.sql).strip()
    ensure_select_sql(sql, require_limit=False)

    result = db.execute(text(sql), plan.params)
    data = [dict(row) for row in result.mappings().all()]
    summary = plan.summary_builder(data)
    return {
        "question": question,
        "sql": sql,
        "summary": summary,
        "data": data,
        "validated_sql_safe": True,
    }
