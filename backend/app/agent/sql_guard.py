from __future__ import annotations

import re

ALLOWED_TABLES = {
    "agent_session",
    "agent_todo",
    "agent_tool_call",
    "crack_identity",
    "crack_record",
    "inspection_task",
    "maintenance_record",
    "media_asset",
    "nl_query_log",
    "road_segment",
}
BLOCKED_KEYWORDS = (
    "insert ",
    "update ",
    "delete ",
    "drop ",
    "alter ",
    "create ",
    "truncate ",
    "pragma ",
    "attach ",
    "detach ",
    "replace ",
)
BLOCKED_INTERNAL_TABLES = {"sqlite_master", "sqlite_schema", "sqlite_temp_master"}


def normalize_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.strip()).lower()


def validate_select_sql(sql: str, *, require_limit: bool = True) -> tuple[bool, str]:
    normalized = normalize_sql(sql)
    padded = f" {normalized} "
    if not normalized.startswith("select "):
        return False, "仅允许执行 SELECT 查询。"
    if ";" in normalized:
        return False, "禁止多语句执行。"
    if any(keyword in padded for keyword in BLOCKED_KEYWORDS):
        return False, "查询包含被禁止的写操作或高风险关键字。"
    if any(table in padded for table in BLOCKED_INTERNAL_TABLES):
        return False, "禁止访问 SQLite 内部系统表。"

    referenced_tables = {
        match.group(1)
        for match in re.finditer(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", normalized)
    }
    unexpected_tables = sorted(table for table in referenced_tables if table not in ALLOWED_TABLES)
    if unexpected_tables:
        return False, f"查询访问了未授权数据表: {', '.join(unexpected_tables)}"

    has_limit = " limit " in padded
    is_scalar_aggregate = bool(re.search(r"\b(count|sum|avg|max|min)\s*\(", normalized))
    if require_limit and not has_limit and not is_scalar_aggregate:
        return False, "查询必须带 LIMIT 限制返回行数。"
    return True, "ok"


def ensure_select_sql(sql: str, *, require_limit: bool = True) -> None:
    is_valid, message = validate_select_sql(sql, require_limit=require_limit)
    if not is_valid:
        raise PermissionError(message)
