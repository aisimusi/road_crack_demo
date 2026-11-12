from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app import models
from app.agent.llm_client import LLMResponse, ToolCallRequest, build_llm_client, infer_debug_intent
from app.agent.prompts import build_final_answer_prompt, build_maintenance_decision_prompt, build_system_prompt
from app.agent.todo_manager import create_initial_todos, finalize_todos, update_todos_for_tool
from app.agent.tool_registry import ToolRegistry, build_default_registry

MAX_AGENT_STEPS = 20
EMPTY_GEOJSON = {"type": "FeatureCollection", "features": []}


def _utcnow() -> datetime:
    return datetime.utcnow()


def _safe_json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def _safe_json_loads(text: str | None) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _record_tool_call(
    db: Session,
    *,
    session_id: int,
    tool_name: str,
    tool_args: dict[str, Any],
    tool_result: dict[str, Any] | None,
    status_text: str,
    error_message: str | None = None,
) -> models.AgentToolCall:
    tool_call = models.AgentToolCall(
        session_id=session_id,
        tool_name=tool_name,
        tool_args=_safe_json_dumps(tool_args),
        tool_result=_safe_json_dumps(tool_result) if tool_result is not None else None,
        status=status_text,
        error_message=error_message,
    )
    db.add(tool_call)
    db.flush()
    return tool_call


def _serialize_tool_call(tool_call: models.AgentToolCall) -> dict[str, Any]:
    tool_args = _safe_json_loads(tool_call.tool_args)
    tool_result = _safe_json_loads(tool_call.tool_result)
    return {
        "id": tool_call.id,
        "session_id": tool_call.session_id,
        "tool_name": tool_call.tool_name,
        "tool_args": tool_args if isinstance(tool_args, dict) else {},
        "tool_result": tool_result if isinstance(tool_result, dict) else None,
        "status": tool_call.status,
        "error_message": tool_call.error_message,
        "created_at": tool_call.created_at,
    }


def _serialize_todo(todo: models.AgentTodo) -> dict[str, Any]:
    return {
        "id": todo.id,
        "session_id": todo.session_id,
        "content": todo.content,
        "status": todo.status,
        "step_order": todo.step_order,
        "created_at": todo.created_at,
        "updated_at": todo.updated_at,
    }


def _last_tool_result(observations: list[dict[str, Any]], tool_name: str) -> dict[str, Any] | None:
    for item in reversed(observations):
        if item.get("tool_name") == tool_name and item.get("status") == "success":
            result = item.get("result")
            if isinstance(result, dict):
                return result
    return None


def _merge_result_payload(payload: dict[str, Any], tool_name: str, result: dict[str, Any]) -> None:
    if tool_name in {"aggregate_crack_stats", "compare_crack_stats", "rank_roads_by_risk"}:
        payload["stats"] = result
    elif tool_name in {"query_cracks", "find_high_risk_cracks", "query_crack_identities"}:
        payload["cracks"] = result.get("items", [])
    elif tool_name == "get_crack_identity_timeline":
        payload["identity_timeline"] = result
    elif tool_name == "build_map_geojson":
        payload["map_geojson"] = result
    elif tool_name == "get_crack_images":
        payload["images"] = result.get("images", [])
    elif tool_name == "analyze_crack_images":
        payload["image_analysis"] = result
    elif tool_name == "generate_maintenance_advice":
        payload["maintenance_advice"] = result
    elif tool_name == "resolve_query_context":
        payload["resolved_context"] = result
    elif tool_name == "resolve_place":
        payload["resolved_place"] = result
    elif tool_name == "analyze_surrounding_pois":
        payload["poi_context"] = result


def _derive_used_crack_ids(payload: dict[str, Any]) -> list[int]:
    crack_ids: list[int] = []
    for item in payload.get("cracks", [])[:6]:
        if "id" in item:
            crack_ids.append(int(item["id"]))
    return crack_ids


def _has_answerable_observations(response_payload: dict[str, Any]) -> bool:
    return bool(
        response_payload.get("cracks")
        or response_payload.get("stats")
        or response_payload.get("maintenance_advice")
        or response_payload.get("map_geojson", {}).get("features")
    )


def _stream_event(event_type: str, content: str = "", **extra: Any) -> dict[str, Any]:
    payload = {"type": event_type, "content": content}
    payload.update(extra)
    return payload


def _stringify_error(exc: Exception) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__


def _first_step_needs_tool(response: LLMResponse, step_index: int, observations: list[dict[str, Any]]) -> bool:
    return step_index == 0 and not observations and not response.tool_calls


def _tool_result_message(tool_call_id: str, tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "name": tool_name,
        "content": _safe_json_dumps(result),
    }


def _priority_rank(level: str) -> int:
    return {"低": 1, "中": 2, "高": 3}.get(level, 1)


def _constrain_priority_level(selected: str, upper_bound: str) -> str:
    return selected if _priority_rank(selected) <= _priority_rank(upper_bound) else upper_bound


def _refine_maintenance_advice_with_llm(
    llm_client,
    *,
    registry: ToolRegistry,
    user_query: str,
    stats: dict[str, Any],
    top_cracks: list[dict[str, Any]],
    rule_advice: dict[str, Any],
) -> dict[str, Any]:
    prompt = build_maintenance_decision_prompt(
        user_query=user_query,
        stats=stats,
        top_cracks=top_cracks,
        rule_advice=rule_advice,
    )
    response = llm_client.generate(
        messages=[
            {"role": "system", "content": build_system_prompt(registry)},
            {"role": "user", "content": prompt},
        ],
        tools_schema=[],
        runtime={"stage": "maintenance_refine"},
    )
    if response.tool_calls:
        raise RuntimeError("维修建议细化阶段不应调用工具。")
    payload = _safe_json_loads((response.content or "").strip())
    if not isinstance(payload, dict):
        raise RuntimeError("模型未返回合法的维修建议 JSON。")

    refined_priority = _constrain_priority_level(
        str(payload.get("priority_level") or rule_advice.get("priority_level") or "低"),
        str(rule_advice.get("max_priority_level") or rule_advice.get("priority_level") or "低"),
    )
    refined_actions = [
        str(item).strip()
        for item in (payload.get("actions") or [])
        if str(item).strip()
    ][:4] or list(rule_advice.get("actions") or [])[:4]
    refined_reason_factors = [
        str(item).strip()
        for item in (payload.get("reason_factors") or [])
        if str(item).strip()
    ][:5] or list(rule_advice.get("reason_factors") or [])[:5]

    return {
        **rule_advice,
        "priority_level": refined_priority,
        "summary": str(payload.get("summary") or rule_advice.get("summary") or "").strip() or rule_advice.get("summary", ""),
        "actions": refined_actions,
        "reason_factors": refined_reason_factors,
        "decision_mode": "hybrid_llm_refined",
    }


def _assistant_message(response: LLMResponse) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": response.role,
        "content": response.content or "",
    }
    if response.tool_calls:
        payload["tool_calls"] = [
            {
                "id": item.id,
                "type": "function",
                "function": {
                    "name": item.name,
                    "arguments": _safe_json_dumps(item.arguments),
                },
            }
            for item in response.tool_calls
        ]
    return payload


def _auto_attach_assets(
    db: Session,
    *,
    registry: ToolRegistry,
    session_id: int,
    payload: dict[str, Any],
    observations: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    used_crack_ids: list[int],
) -> None:
    if not used_crack_ids:
        return

    if not payload.get("map_geojson", {}).get("features"):
        result = registry.call(db, "build_map_geojson", {"crack_ids": used_crack_ids})
        _record_tool_call(
            db,
            session_id=session_id,
            tool_name="build_map_geojson",
            tool_args={"crack_ids": used_crack_ids},
            tool_result=result,
            status_text="success",
        )
        observations.append(
            {
                "tool_name": "build_map_geojson",
                "arguments": {"crack_ids": used_crack_ids},
                "result": result,
                "status": "success",
            }
        )
        _merge_result_payload(payload, "build_map_geojson", result)
        messages.append(_tool_result_message("auto-build-map", "build_map_geojson", result))

    if not payload.get("images"):
        result = registry.call(db, "get_crack_images", {"crack_ids": used_crack_ids})
        _record_tool_call(
            db,
            session_id=session_id,
            tool_name="get_crack_images",
            tool_args={"crack_ids": used_crack_ids},
            tool_result=result,
            status_text="success",
        )
        observations.append(
            {
                "tool_name": "get_crack_images",
                "arguments": {"crack_ids": used_crack_ids},
                "result": result,
                "status": "success",
            }
        )
        _merge_result_payload(payload, "get_crack_images", result)
        messages.append(_tool_result_message("auto-get-images", "get_crack_images", result))


def _ensure_image_analysis(
    db: Session,
    *,
    session: models.AgentSession,
    registry: ToolRegistry,
    response_payload: dict[str, Any],
    observations: list[dict[str, Any]],
    messages: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if response_payload.get("image_analysis"):
        return response_payload.get("image_analysis")

    crack_ids = [int(item["id"]) for item in response_payload.get("cracks", [])[:3] if "id" in item]
    if not crack_ids:
        return None

    result = registry.call(db, "analyze_crack_images", {"crack_ids": crack_ids, "max_images": 3})
    _record_tool_call(
        db,
        session_id=session.id,
        tool_name="analyze_crack_images",
        tool_args={"crack_ids": crack_ids, "max_images": 3},
        tool_result=result,
        status_text="success",
    )
    observations.append(
        {
            "tool_name": "analyze_crack_images",
            "arguments": {"crack_ids": crack_ids, "max_images": 3},
            "result": result,
            "status": "success",
        }
    )
    _merge_result_payload(response_payload, "analyze_crack_images", result)
    messages.append(_tool_result_message("auto-analyze-images", "analyze_crack_images", result))
    db.commit()
    return result


def _generate_final_answer(
    llm_client,
    *,
    registry: ToolRegistry,
    user_query: str,
    response_payload: dict[str, Any],
    observations: list[dict[str, Any]],
) -> str:
    messages = [
        {"role": "system", "content": build_system_prompt(registry)},
        {
            "role": "user",
            "content": build_final_answer_prompt(
                user_query=user_query,
                response_payload=response_payload,
                observations=observations,
            ),
        },
    ]
    response = llm_client.generate(messages=messages, tools_schema=[], runtime={"stage": "final_answer"})
    if response.tool_calls:
        raise RuntimeError("最终回答阶段不应再调用工具。")
    answer = (response.content or "").strip()
    if not answer:
        raise RuntimeError("LLM 未返回最终回答。")
    return answer


def _build_final_answer_fallback(
    *,
    user_query: str,
    response_payload: dict[str, Any],
) -> str:
    lines: list[str] = []
    stats = response_payload.get("stats") if isinstance(response_payload.get("stats"), dict) else {}
    cracks = response_payload.get("cracks") if isinstance(response_payload.get("cracks"), list) else []
    maintenance_advice = (
        response_payload.get("maintenance_advice")
        if isinstance(response_payload.get("maintenance_advice"), dict)
        else {}
    )

    if stats:
        total_count = stats.get("total_count")
        severe_count = stats.get("severe_count") or stats.get("serious_count")
        road_distribution = stats.get("road_distribution") or []
        if total_count is not None:
            summary = f"根据当前查询结果，共发现 {total_count} 条裂缝记录"
            if severe_count is not None:
                summary += f"，其中严重裂缝 {severe_count} 条"
            if road_distribution:
                lead = road_distribution[0]
                road_name = lead.get("road_name")
                road_count = lead.get("count")
                if road_name and road_count is not None:
                    summary += f"，重点集中在 {road_name}（{road_count} 条）"
            summary += "。"
            lines.append(summary)

    if cracks:
        top = cracks[:3]
        crack_parts = []
        for item in top:
            crack_id = item.get("crack_code") or item.get("identity_code") or f"ID {item.get('id')}"
            road_name = item.get("road_name") or "未知道路"
            severity_label = item.get("severity_label") or "未知等级"
            crack_parts.append(f"{crack_id}（{road_name}，{severity_label}）")
        if crack_parts:
            lines.append(f"重点裂缝包括：{'；'.join(crack_parts)}。")

    if maintenance_advice:
        priority = maintenance_advice.get("priority_level") or "未评定"
        label = maintenance_advice.get("maintenance_label") or "未提供"
        summary = str(maintenance_advice.get("summary") or "").strip()
        lines.append(f"维修优先级：{priority}，建议处置方式：{label}。")
        if summary:
            lines.append(summary)

    if not lines:
        lines.append(f"已完成“{user_query}”的查询，但当前结果中没有足够数据可生成详细结论。")

    return "\n".join(lines)


def _execute_tool_calls(
    *,
    db: Session,
    session: models.AgentSession,
    registry: ToolRegistry,
    response: LLMResponse,
    response_payload: dict[str, Any],
    observations: list[dict[str, Any]],
    messages: list[dict[str, Any]],
) -> None:
    messages.append(_assistant_message(response))
    for tool_call in response.tool_calls:
        try:
            result = registry.call(db, tool_call.name, tool_call.arguments)
            call_status = "success"
            error_message = None
            _merge_result_payload(response_payload, tool_call.name, result)
        except Exception as exc:
            result = {"error": str(exc)}
            call_status = "failed"
            error_message = str(exc)

        _record_tool_call(
            db,
            session_id=session.id,
            tool_name=tool_call.name,
            tool_args=tool_call.arguments,
            tool_result=result,
            status_text=call_status,
            error_message=error_message,
        )
        update_todos_for_tool(db, session.id, tool_call.name, result, status=call_status)
        db.commit()

        observation = {
            "tool_name": tool_call.name,
            "arguments": tool_call.arguments,
            "result": result,
            "status": call_status,
        }
        observations.append(observation)
        messages.append(_tool_result_message(tool_call.id, tool_call.name, result))


def _ensure_poi_context(
    db: Session,
    *,
    session: models.AgentSession,
    registry: ToolRegistry,
    response_payload: dict[str, Any],
    observations: list[dict[str, Any]],
    messages: list[dict[str, Any]],
) -> None:
    if response_payload.get("poi_context"):
        return

    crack_ids = [int(item["id"]) for item in response_payload.get("cracks", [])[:3] if "id" in item]
    if not crack_ids:
        return

    result = registry.call(db, "analyze_surrounding_pois", {"crack_ids": crack_ids})
    _record_tool_call(
        db,
        session_id=session.id,
        tool_name="analyze_surrounding_pois",
        tool_args={"crack_ids": crack_ids},
        tool_result=result,
        status_text="success",
    )
    observations.append(
        {
            "tool_name": "analyze_surrounding_pois",
            "arguments": {"crack_ids": crack_ids},
            "result": result,
            "status": "success",
        }
    )
    _merge_result_payload(response_payload, "analyze_surrounding_pois", result)
    messages.append(_tool_result_message("auto-analyze-pois", "analyze_surrounding_pois", result))
    db.commit()


def _ensure_maintenance_advice(
    db: Session,
    *,
    session: models.AgentSession,
    registry: ToolRegistry,
    llm_client,
    user_query: str,
    response_payload: dict[str, Any],
    observations: list[dict[str, Any]],
    fallback_used: bool,
    fallback_reason: str | None,
) -> tuple[bool, str | None]:
    if not response_payload.get("cracks") or response_payload.get("maintenance_advice"):
        return fallback_used, fallback_reason

    stats = response_payload["stats"] if isinstance(response_payload["stats"], dict) else {}
    if response_payload.get("poi_context"):
        stats = {
            **stats,
            "poi_context": response_payload["poi_context"],
        }
    top_cracks = response_payload["cracks"][:5]
    advice = registry.call(db, "generate_maintenance_advice", {"stats": stats, "top_cracks": top_cracks})
    try:
        advice = _refine_maintenance_advice_with_llm(
            llm_client,
            registry=registry,
            user_query=user_query,
            stats=stats,
            top_cracks=top_cracks,
            rule_advice=advice,
        )
    except Exception as exc:
        fallback_used = True
        reason = f"maintenance_refine_failed: {_stringify_error(exc)}"
        fallback_reason = f"{fallback_reason}; {reason}" if fallback_reason else reason
    _record_tool_call(
        db,
        session_id=session.id,
        tool_name="generate_maintenance_advice",
        tool_args={"stats": stats, "top_cracks": top_cracks},
        tool_result=advice,
        status_text="success",
    )
    update_todos_for_tool(db, session.id, "generate_maintenance_advice", advice, status="success")
    response_payload["maintenance_advice"] = advice
    observations.append(
        {
            "tool_name": "generate_maintenance_advice",
            "arguments": {"stats": stats, "top_cracks": top_cracks},
            "result": advice,
            "status": "success",
        }
    )
    db.commit()
    return fallback_used, fallback_reason


def _finish_agent_session(
    db: Session,
    *,
    session: models.AgentSession,
    user_query: str,
    final_answer: str,
    response_payload: dict[str, Any],
    fallback_used: bool,
    fallback_reason: str | None,
) -> dict[str, Any]:
    finalize_todos(
        db,
        session.id,
        has_map=bool(response_payload["map_geojson"].get("features")),
        has_images=bool(response_payload["images"]),
        fallback_used=fallback_used,
    )

    session.final_answer = final_answer
    session.status = "finished"
    session.finished_at = _utcnow()
    db.commit()

    return _collect_session_payload(
        db,
        session=session,
        user_query=user_query,
        answer=final_answer,
        response_payload=response_payload,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
    )


def _collect_session_payload(
    db: Session,
    *,
    session: models.AgentSession,
    user_query: str,
    answer: str,
    response_payload: dict[str, Any],
    fallback_used: bool = False,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    todos = (
        db.query(models.AgentTodo)
        .filter(models.AgentTodo.session_id == session.id)
        .order_by(models.AgentTodo.step_order.asc())
        .all()
    )
    tool_calls = (
        db.query(models.AgentToolCall)
        .filter(models.AgentToolCall.session_id == session.id)
        .order_by(models.AgentToolCall.id.asc())
        .all()
    )
    return {
        "session_id": session.id,
        "query": user_query,
        "answer": answer,
        "todos": [_serialize_todo(todo) for todo in todos],
        "tool_calls": [_serialize_tool_call(tool_call) for tool_call in tool_calls],
        "stats": response_payload.get("stats", {}),
        "cracks": response_payload.get("cracks", []),
        "images": response_payload.get("images", []),
        "image_analysis": response_payload.get("image_analysis", {}),
        "map_geojson": response_payload.get("map_geojson", EMPTY_GEOJSON),
        "maintenance_advice": response_payload.get("maintenance_advice", {}),
        "debug": {
            "llm_mode": session.llm_mode,
            "steps": len(tool_calls),
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "intent": session.debug_intent,
            "generated_at": _utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        },
    }


def run_agent_query(db: Session, user_query: str) -> dict[str, Any]:
    llm_client = build_llm_client()
    registry = build_default_registry()
    fallback_used = False
    fallback_reason: str | None = None

    session = models.AgentSession(
        user_query=user_query,
        status="running",
        llm_mode=llm_client.mode,
        debug_intent=infer_debug_intent(user_query),
    )
    db.add(session)
    db.flush()
    create_initial_todos(db, session.id)
    db.commit()

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_system_prompt(registry)},
        {"role": "user", "content": user_query},
    ]
    observations: list[dict[str, Any]] = []
    response_payload: dict[str, Any] = {
        "stats": {},
        "cracks": [],
        "images": [],
        "image_analysis": {},
        "map_geojson": EMPTY_GEOJSON,
        "maintenance_advice": {},
        "resolved_context": {},
        "resolved_place": {},
        "poi_context": {},
    }

    for step_index in range(MAX_AGENT_STEPS):
        response = llm_client.generate(
            messages=messages,
            tools_schema=registry.openai_tools(),
            runtime={
                "query": user_query,
                "observations": observations,
                "step": step_index + 1,
                "require_tool": step_index == 0,
            },
        )
        if _first_step_needs_tool(response, step_index, observations):
            messages.append(_assistant_message(response))
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "请先调用至少一个最合适的工具获取真实 Observation，"
                        "再继续分析；当前不能直接给出最终结论。"
                    ),
                }
            )
            continue
        if response.tool_calls:
            _execute_tool_calls(
                db=db,
                session=session,
                registry=registry,
                response=response,
                response_payload=response_payload,
                observations=observations,
                messages=messages,
            )
            continue

        if response.content.strip():
            break
    else:
        if not _has_answerable_observations(response_payload):
            raise RuntimeError("Agent 在最大步数内未完成工具规划。")
        fallback_used = True
        fallback_reason = "max_steps_reached_with_observations"

    used_crack_ids = _derive_used_crack_ids(response_payload)
    if used_crack_ids:
        _auto_attach_assets(
            db,
            registry=registry,
            session_id=session.id,
            payload=response_payload,
            observations=observations,
            messages=messages,
            used_crack_ids=used_crack_ids,
        )
        try:
            _ensure_image_analysis(
                db,
                session=session,
                registry=registry,
                response_payload=response_payload,
                observations=observations,
                messages=messages,
            )
        except Exception as exc:
            fallback_used = True
            reason = f"image_analysis_failed: {_stringify_error(exc)}"
            fallback_reason = f"{fallback_reason}; {reason}" if fallback_reason else reason

    if response_payload.get("cracks") and not response_payload.get("maintenance_advice"):
        _ensure_poi_context(
            db,
            session=session,
            registry=registry,
            response_payload=response_payload,
            observations=observations,
            messages=messages,
        )
        stats = response_payload["stats"] if isinstance(response_payload["stats"], dict) else {}
        if response_payload.get("poi_context"):
            stats = {
                **stats,
                "poi_context": response_payload["poi_context"],
            }
        fallback_used, fallback_reason = _ensure_maintenance_advice(
            db,
            session=session,
            registry=registry,
            llm_client=llm_client,
            user_query=user_query,
            response_payload=response_payload,
            observations=observations,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
        )

    try:
        final_answer = _generate_final_answer(
            llm_client,
            registry=registry,
            user_query=user_query,
            response_payload=response_payload,
            observations=observations,
        )
    except Exception as exc:
        final_answer = _build_final_answer_fallback(user_query=user_query, response_payload=response_payload)
        fallback_used = True
        reason = f"final_answer_failed: {_stringify_error(exc)}"
        fallback_reason = f"{fallback_reason}; {reason}" if fallback_reason else reason

    return _finish_agent_session(
        db,
        session=session,
        user_query=user_query,
        final_answer=final_answer,
        response_payload=response_payload,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
    )


def run_agent_query_stream(db: Session, user_query: str):
    llm_client = build_llm_client()
    registry = build_default_registry()
    fallback_used = False
    fallback_reason: str | None = None

    session = models.AgentSession(
        user_query=user_query,
        status="running",
        llm_mode=llm_client.mode,
        debug_intent=infer_debug_intent(user_query),
    )
    db.add(session)
    db.flush()
    create_initial_todos(db, session.id)
    db.commit()

    yield _stream_event("session", session_id=session.id, llm_mode=llm_client.mode)
    yield _stream_event("thinking_step", "已创建 Agent 会话，开始理解问题。")

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_system_prompt(registry)},
        {"role": "user", "content": user_query},
    ]
    observations: list[dict[str, Any]] = []
    response_payload: dict[str, Any] = {
        "stats": {},
        "cracks": [],
        "images": [],
        "image_analysis": {},
        "map_geojson": EMPTY_GEOJSON,
        "maintenance_advice": {},
        "resolved_context": {},
        "resolved_place": {},
        "poi_context": {},
    }

    final_response: LLMResponse | None = None
    for step_index in range(MAX_AGENT_STEPS):
        yield _stream_event("thinking_step", f"第 {step_index + 1} 步：请求模型判断下一步动作。")
        streamed_response: LLMResponse | None = None
        for event in llm_client.stream_generate(
            messages=messages,
            tools_schema=registry.openai_tools(),
            runtime={
                "query": user_query,
                "observations": observations,
                "step": step_index + 1,
                "require_tool": step_index == 0,
            },
        ):
            event_type = event.get("type")
            if event_type == "thinking":
                yield _stream_event("thinking_delta", str(event.get("content") or ""))
            elif event_type == "answer":
                content = str(event.get("content") or "")
                if content:
                    yield _stream_event("reasoning_answer_delta", content)
            elif event_type == "complete":
                streamed_response = event.get("response")

        if streamed_response is None:
            raise RuntimeError("流式 LLM 未返回完整响应。")

        if _first_step_needs_tool(streamed_response, step_index, observations):
            yield _stream_event("thinking_step", "模型首轮未调用工具，已追加约束提示并重试。")
            messages.append(_assistant_message(streamed_response))
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "请先调用至少一个最合适的工具获取真实 Observation，"
                        "再继续分析；当前不能直接给出最终结论。"
                    ),
                }
            )
            continue

        if streamed_response.tool_calls:
            yield _stream_event(
                "thinking_step",
                "模型已选择下一批工具，开始执行。",
                tool_names=[item.name for item in streamed_response.tool_calls],
            )
            _execute_tool_calls(
                db=db,
                session=session,
                registry=registry,
                response=streamed_response,
                response_payload=response_payload,
                observations=observations,
                messages=messages,
            )
            for tool_call in streamed_response.tool_calls:
                latest = observations[-len(streamed_response.tool_calls):]
                matched = next((item for item in latest if item["tool_name"] == tool_call.name), None)
                if matched:
                    yield _stream_event(
                        "tool_result",
                        f"{tool_call.name} 执行完成，状态：{matched['status']}。",
                        tool_name=tool_call.name,
                        status=matched["status"],
                        result=matched["result"],
                    )
            continue

        final_response = streamed_response
        break
    else:
        if not _has_answerable_observations(response_payload):
            raise RuntimeError("Agent 在最大步数内未完成工具规划。")
        fallback_used = True
        fallback_reason = "max_steps_reached_with_observations"
        yield _stream_event("thinking_step", "模型规划步数已达上限，已使用现有 Observation 收束回答。")

    used_crack_ids = _derive_used_crack_ids(response_payload)
    if used_crack_ids:
        yield _stream_event("thinking_step", "已根据重点裂缝自动补充地图点位与代表性图片。")
        _auto_attach_assets(
            db,
            registry=registry,
            session_id=session.id,
            payload=response_payload,
            observations=observations,
            messages=messages,
            used_crack_ids=used_crack_ids,
        )
        yield _stream_event("thinking_step", "已提取代表性裂缝图片，尝试交由视觉模型辅助判读。")
        try:
            image_analysis = _ensure_image_analysis(
                db,
                session=session,
                registry=registry,
                response_payload=response_payload,
                observations=observations,
                messages=messages,
            )
            if image_analysis and image_analysis.get("enabled"):
                yield _stream_event("thinking_step", "视觉模型已返回裂缝图片判读结果。")
            elif image_analysis and image_analysis.get("message"):
                yield _stream_event("thinking_step", str(image_analysis.get("message")))
        except Exception as exc:
            fallback_used = True
            reason = f"image_analysis_failed: {_stringify_error(exc)}"
            fallback_reason = f"{fallback_reason}; {reason}" if fallback_reason else reason
            yield _stream_event("thinking_step", "裂缝图片视觉分析失败，已跳过该步骤。")

    if response_payload.get("cracks") and not response_payload.get("maintenance_advice"):
        yield _stream_event("thinking_step", "已根据重点裂缝自动分析周边敏感设施。")
        _ensure_poi_context(
            db,
            session=session,
            registry=registry,
            response_payload=response_payload,
            observations=observations,
            messages=messages,
        )
        yield _stream_event("thinking_step", "已生成规则基础维修建议，尝试交由模型在约束内细化。")
        before_fallback = fallback_used
        fallback_used, fallback_reason = _ensure_maintenance_advice(
            db,
            session=session,
            registry=registry,
            llm_client=llm_client,
            user_query=user_query,
            response_payload=response_payload,
            observations=observations,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
        )
        if response_payload.get("maintenance_advice") and not (fallback_used and not before_fallback):
            yield _stream_event("thinking_step", "模型已在标准约束内完成维修建议细化。")
        elif fallback_used and not before_fallback:
            yield _stream_event("thinking_step", "维修建议已使用后端规则结果。")

    streamed_answer = (final_response.content or "").strip() if final_response else ""
    if streamed_answer:
        final_answer = streamed_answer
    else:
        try:
            final_answer = _generate_final_answer(
                llm_client,
                registry=registry,
                user_query=user_query,
                response_payload=response_payload,
                observations=observations,
            )
        except Exception as exc:
            final_answer = _build_final_answer_fallback(user_query=user_query, response_payload=response_payload)
            fallback_used = True
            reason = f"final_answer_failed: {_stringify_error(exc)}"
            fallback_reason = f"{fallback_reason}; {reason}" if fallback_reason else reason

    final_payload = _finish_agent_session(
        db,
        session=session,
        user_query=user_query,
        final_answer=final_answer,
        response_payload=response_payload,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
    )
    if not streamed_answer:
        for char in final_answer:
            yield _stream_event("answer_delta", char)
    yield _stream_event("final", data=final_payload)
    yield _stream_event("done")


def get_agent_session_detail(db: Session, session_id: int) -> dict[str, Any]:
    session = db.get(models.AgentSession, session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent 会话不存在")

    todos = (
        db.query(models.AgentTodo)
        .filter(models.AgentTodo.session_id == session_id)
        .order_by(models.AgentTodo.step_order.asc())
        .all()
    )
    tool_calls = (
        db.query(models.AgentToolCall)
        .filter(models.AgentToolCall.session_id == session_id)
        .order_by(models.AgentToolCall.id.asc())
        .all()
    )
    tool_observations = [
        {
            "tool_name": tool_call.tool_name,
            "status": tool_call.status,
            "result": _safe_json_loads(tool_call.tool_result) if tool_call.tool_result else None,
        }
        for tool_call in tool_calls
    ]

    latest_stats = _last_tool_result(
        tool_observations,
        "aggregate_crack_stats",
    ) or _last_tool_result(
        tool_observations,
        "rank_roads_by_risk",
    ) or _last_tool_result(
        tool_observations,
        "compare_crack_stats",
    )
    latest_cracks = _last_tool_result(tool_observations, "query_cracks") or _last_tool_result(
        tool_observations,
        "find_high_risk_cracks",
    ) or _last_tool_result(tool_observations, "query_crack_identities")
    latest_images = _last_tool_result(tool_observations, "get_crack_images")
    latest_map_geojson = _last_tool_result(tool_observations, "build_map_geojson")
    latest_maintenance_advice = _last_tool_result(tool_observations, "generate_maintenance_advice")
    latest_image_analysis = _last_tool_result(tool_observations, "analyze_crack_images")

    return {
        "session_id": session.id,
        "query": session.user_query,
        "answer": session.final_answer or "",
        "todos": [_serialize_todo(todo) for todo in todos],
        "tool_calls": [_serialize_tool_call(tool_call) for tool_call in tool_calls],
        "stats": latest_stats or {},
        "cracks": (latest_cracks or {}).get("items", []) if isinstance(latest_cracks, dict) else [],
        "images": (latest_images or {}).get("images", []) if isinstance(latest_images, dict) else [],
        "image_analysis": latest_image_analysis or {},
        "map_geojson": latest_map_geojson or EMPTY_GEOJSON,
        "maintenance_advice": latest_maintenance_advice or {},
        "created_at": session.created_at,
        "finished_at": session.finished_at,
        "debug": {
            "llm_mode": session.llm_mode,
            "status": session.status,
            "intent": session.debug_intent,
        },
    }
