from __future__ import annotations

from sqlalchemy.orm import Session

from app import models

INITIAL_TODO_STEPS = [
    "理解用户查询需求",
    "选择需要调用的数据工具",
    "查询裂缝检测数据",
    "生成地图和图片证据",
    "形成最终分析回答",
]


def create_initial_todos(db: Session, session_id: int) -> list[models.AgentTodo]:
    todos = []
    for index, content in enumerate(INITIAL_TODO_STEPS, start=1):
        status = "in_progress" if index == 1 else "pending"
        todos.append(
            models.AgentTodo(
                session_id=session_id,
                content=content,
                status=status,
                step_order=index,
            )
        )
    db.add_all(todos)
    db.flush()
    return todos


def _get_todos(db: Session, session_id: int) -> list[models.AgentTodo]:
    return (
        db.query(models.AgentTodo)
        .filter(models.AgentTodo.session_id == session_id)
        .order_by(models.AgentTodo.step_order.asc())
        .all()
    )


def update_todos_for_tool(
    db: Session,
    session_id: int,
    tool_name: str,
    result: dict,
    *,
    status: str,
) -> None:
    todos = _get_todos(db, session_id)
    todo_map = {todo.step_order: todo for todo in todos}
    step1 = todo_map[1]
    step2 = todo_map[2]
    step3 = todo_map[3]
    step4 = todo_map[4]
    step5 = todo_map[5]

    step1.status = "completed"
    step1.content = "已理解用户查询需求"

    if status == "failed":
        if step5.status == "pending":
            step5.status = "in_progress"
        step5.content = f"工具 {tool_name} 调用失败，系统正在尝试兜底回答"
        return

    if tool_name in {"inspect_schema", "list_roads", "find_road", "parse_time_range", "resolve_place"}:
        step2.status = "completed"
        if tool_name == "parse_time_range":
            label = result.get("label") or "已完成时间解析"
            step2.content = f"已解析查询时间范围：{label}"
        elif tool_name == "resolve_place":
            selected = result.get("selected") or {}
            place_name = selected.get("name") or result.get("requested")
            radius_m = selected.get("radius_m") or result.get("radius_m")
            step2.content = f"已解析地点范围：{place_name} 周边 {radius_m} 米" if place_name else "已尝试解析地点范围"
        elif tool_name == "find_road":
            road_name = (result.get("road") or {}).get("name")
            step2.content = f"已确认道路范围：{road_name}" if road_name else "已尝试确认道路范围"
        elif tool_name == "list_roads":
            step2.content = "已列出系统支持查询的道路"
        else:
            step2.content = "已识别可查询的数据结构"
        if step3.status == "pending":
            step3.status = "in_progress"

    if tool_name in {
        "aggregate_crack_stats",
        "query_cracks",
        "compare_crack_stats",
        "query_crack_identities",
        "find_high_risk_cracks",
        "analyze_surrounding_pois",
    }:
        step2.status = "completed"
        step3.status = "completed"
        if tool_name == "compare_crack_stats":
            step3.content = "已完成裂缝时间对比分析"
        elif tool_name == "aggregate_crack_stats":
            step3.content = "已完成裂缝统计分析"
        elif tool_name == "analyze_surrounding_pois":
            step3.content = "已完成裂缝周边敏感设施分析"
        else:
            step3.content = "已查询裂缝检测记录"
        if step4.status == "pending":
            step4.status = "in_progress"

    if tool_name in {"build_map_geojson", "get_crack_images"}:
        step4.status = "completed"
        if tool_name == "build_map_geojson":
            feature_count = len(result.get("features", []))
            step4.content = f"已生成地图标注数据，共 {feature_count} 个点位"
        else:
            image_count = len(result.get("images", []))
            step4.content = f"已获取裂缝图片证据，共 {image_count} 张"
        if step5.status == "pending":
            step5.status = "in_progress"

    if tool_name == "generate_maintenance_advice":
        step5.status = "in_progress"
        step5.content = "已生成维修建议，正在组织最终分析回答"


def finalize_todos(
    db: Session,
    session_id: int,
    *,
    has_map: bool,
    has_images: bool,
    fallback_used: bool,
) -> None:
    todos = _get_todos(db, session_id)
    todo_map = {todo.step_order: todo for todo in todos}
    todo_map[1].status = "completed"
    todo_map[2].status = "completed"
    if todo_map[3].status == "pending":
        todo_map[3].status = "completed"
        todo_map[3].content = "已完成裂缝数据检查"
    if todo_map[4].status == "pending":
        todo_map[4].status = "completed"
        if has_map or has_images:
            todo_map[4].content = "已补充地图与图片证据"
        else:
            todo_map[4].content = "无可展示点位或图片证据"
    todo_map[5].status = "completed"
    if fallback_used:
        todo_map[5].content = "已基于现有 Observation 生成兜底分析回答"
    else:
        todo_map[5].content = "已形成最终分析回答"
