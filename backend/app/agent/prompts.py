from __future__ import annotations

import json
from datetime import datetime

from app.agent.tool_registry import ToolRegistry


def build_system_prompt(registry: ToolRegistry) -> str:
    today = datetime.now().date().isoformat()
    tool_block = json.dumps(registry.describe_tools(), ensure_ascii=False, indent=2)
    return (
        "你是道路裂缝巡检系统中的智能查询 Agent。\n"
        "你的任务是根据用户问题，使用受控工具完成道路裂缝分析，并输出基于 Observation 的中文结论。\n"
        f"服务器当前日期为 {today}。\n\n"
        "你必须遵守以下规则：\n"
        "1. 你不能直接执行 SQL，也不能假设数据库里存在未查询的数据。\n"
        "2. 你只能通过系统提供的 tools 调用工具，不能伪造工具结果。\n"
        "3. 若信息不足，优先继续调用工具；若信息已足够，再直接给出结论。\n"
        "4. 结论必须严格基于已返回的 Observation，不得编造数量、位置、趋势或维修建议。\n"
        "5. 若道路名、地标或时间表达不明确，应优先调用解析类工具。\n"
        "6. 需要地图或图片证据时，请在结论中明确指出重点道路、裂缝或风险点位。\n"
        "7. 平台以 crack_identity 裂缝单体身份档案为核心对象；当用户询问扩大、复发、已维修、复检、优先处置队列或跨批次变化时，应优先调用 query_crack_identities 和 get_crack_identity_timeline。\n"
        "8. crack_record 是一次巡检观测，crack_identity 是同一裂缝跨批次追踪档案，回答时要区分“观测记录数”和“裂缝单体数”。\n"
        "9. 当用户使用“某学校/医院/园区/地标附近、周边 N 米/公里”等区域表达时，不要把地名当道路名；应先调用 resolve_query_context 或 resolve_place 得到中心点和 radius_m，再把 center_latitude、center_longitude、radius_m 传给 query_cracks/query_crack_identities/aggregate_crack_stats/find_high_risk_cracks。\n"
        "10. 当用户同时要求复检、未闭环、敏感点半径、等级/面积增长和维修优先级时，应组合调用：parse_time_range/resolve_query_context 解析范围，query_crack_identities 获取候选，analyze_surrounding_pois 用高德周边数据验证敏感点距离，再用 build_map_geojson/get_crack_images/generate_maintenance_advice 补充地图、证据图和处置建议。\n"
        "11. 你的文本回答应简洁、专业，并尽量指出风险重点、数量统计、空间位置和维修优先级。\n\n"
        "当前可用工具与 schema 如下：\n"
        f"{tool_block}"
    )


def build_final_answer_prompt(
    *,
    user_query: str,
    response_payload: dict,
    observations: list[dict],
) -> str:
    condensed_observations = [
        {
            "tool_name": item.get("tool_name"),
            "status": item.get("status"),
            "result": item.get("result"),
        }
        for item in observations[-8:]
    ]
    return (
        "请基于以下真实 Observation，为用户生成最终中文回答。\n"
        "要求：\n"
        "1. 只依据给定数据回答。\n"
        "2. 如果存在统计结果，优先总结数量、等级、长度、面积、趋势。\n"
        "3. 如果存在裂缝身份档案，优先说明 identity_code、生命周期状态、维修状态、观测次数、最近变化和优先级。\n"
        "4. 如果存在重点裂缝或高风险道路，明确指出位置和原因。\n"
        "5. 如果存在维修建议或风险评分，说明优先级和依据。\n"
        "6. 不要输出 JSON，只输出最终回答正文。\n\n"
        f"用户问题：{user_query}\n\n"
        f"聚合结果：{json.dumps(response_payload, ensure_ascii=False)}\n\n"
        f"观察记录：{json.dumps(condensed_observations, ensure_ascii=False)}"
    )


def build_maintenance_decision_prompt(
    *,
    user_query: str,
    stats: dict,
    top_cracks: list[dict],
    rule_advice: dict,
) -> str:
    return (
        "请基于以下道路裂缝数据，生成一个受约束的维修建议 JSON。\n"
        "你必须遵守：\n"
        "1. 只能在 rule_advice 给定的技术等级、维修等级、处置标签和优先级边界内决策。\n"
        "2. 不得修改或发明 reference_pci、reference_dr、technical_grade、maintenance_level、maintenance_label。\n"
        "3. priority_level 只能取不高于 rule_advice.max_priority_level 的等级；若数据明显更轻，可下调，但不能上调。\n"
        "4. actions 只能从 rule_advice.action_candidates 中选择、改写或压缩，不能引入与 Observation 无关的新施工措施。\n"
        "5. summary 和 reason_factors 必须严格基于给定数据，不得编造额外数量、道路或时间趋势。\n"
        "6. 只输出 JSON，不要输出 markdown。\n\n"
        "输出字段：\n"
        "{\n"
        '  "priority_level": "低|中|高",\n'
        '  "summary": "string",\n'
        '  "actions": ["string"],\n'
        '  "reason_factors": ["string"]\n'
        "}\n\n"
        f"用户问题：{user_query}\n\n"
        f"stats：{json.dumps(stats, ensure_ascii=False)}\n\n"
        f"top_cracks：{json.dumps(top_cracks, ensure_ascii=False)}\n\n"
        f"rule_advice：{json.dumps(rule_advice, ensure_ascii=False)}"
    )


def build_crack_image_analysis_prompt(*, cracks: list[dict]) -> str:
    return (
        "请结合下面的裂缝图片和结构化字段，输出中文判读结论。\n"
        "要求：\n"
        "1. 只描述图片中直接可见的裂缝形态、边缘状态、连通性、是否疑似扩展，以及图片质量限制。\n"
        "2. 不要发明图片里不可见的材质、深度、内部结构或维修历史。\n"
        "3. 如果图片证据不足，要明确写“仅凭图片无法确认”。\n"
        "4. 输出 3 到 6 行简洁要点，不要输出 JSON，不要用表格。\n\n"
        f"结构化字段：{json.dumps(cracks, ensure_ascii=False)}"
    )
