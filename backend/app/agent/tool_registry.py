from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.agent import tools

ToolHandler = Callable[[Session, BaseModel], dict[str, Any]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: ToolHandler
    output_hint: str

    def schema(self) -> dict[str, Any]:
        return self.args_model.model_json_schema()

    def openai_tool_schema(self) -> dict[str, Any]:
        schema = self.schema()
        schema.setdefault("type", "object")
        schema.setdefault("additionalProperties", False)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "strict": True,
                "parameters": schema,
            },
        }


class ToolRegistry:
    def __init__(self, definitions: list[ToolDefinition]):
        self._definitions = {item.name: item for item in definitions}

    def has_tool(self, tool_name: str) -> bool:
        return tool_name in self._definitions

    def get(self, tool_name: str) -> ToolDefinition:
        if tool_name not in self._definitions:
            raise PermissionError(f"未注册工具: {tool_name}")
        return self._definitions[tool_name]

    def describe_tools(self) -> list[dict[str, Any]]:
        descriptions = []
        for item in self._definitions.values():
            descriptions.append(
                {
                    "name": item.name,
                    "description": item.description,
                    "input_schema": item.schema(),
                    "output_hint": item.output_hint,
                }
            )
        return descriptions

    def openai_tools(self) -> list[dict[str, Any]]:
        return [item.openai_tool_schema() for item in self._definitions.values()]

    def validate_arguments(self, tool_name: str, arguments: dict[str, Any]) -> BaseModel:
        definition = self.get(tool_name)
        try:
            return definition.args_model.model_validate(arguments or {})
        except ValidationError as exc:
            raise ValueError(f"工具参数校验失败: {exc.errors()}") from exc

    def call(self, db: Session, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        definition = self.get(tool_name)
        validated = self.validate_arguments(tool_name, arguments)
        return definition.handler(db, validated)


def build_default_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            ToolDefinition(
                name="inspect_schema",
                description="查看当前可查询的数据表、字段和字段含义。",
                args_model=tools.EmptyArgs,
                handler=tools.inspect_schema_tool,
                output_hint="返回 tables 列表和字段描述。",
            ),
            ToolDefinition(
                name="list_roads",
                description="列出系统中当前可查询的道路。",
                args_model=tools.EmptyArgs,
                handler=tools.list_roads_tool,
                output_hint="返回 roads 列表。",
            ),
            ToolDefinition(
                name="find_road",
                description="根据道路名称进行精确或模糊匹配。",
                args_model=tools.FindRoadArgs,
                handler=tools.find_road_tool,
                output_hint="返回 matched、road、candidates。",
            ),
            ToolDefinition(
                name="parse_time_range",
                description="把自然语言时间表达解析为标准日期范围。",
                args_model=tools.ParseTimeRangeArgs,
                handler=tools.parse_time_range_tool,
                output_hint="返回 start_date、end_date、label。",
            ),
            ToolDefinition(
                name="resolve_query_context",
                description="从自然语言中解析道路、地标、地点范围和时间范围，形成查询上下文。",
                args_model=tools.ResolveQueryContextArgs,
                handler=tools.resolve_query_context_tool,
                output_hint="返回 time_range、road_hint、landmark_hint、place_hint、radius_m、road_match、place_match。",
            ),
            ToolDefinition(
                name="resolve_place",
                description="调用高德地点检索，把学校、医院、园区、商圈等地名解析为中心经纬度和建议半径；用于“某地附近/周边N米”的空间查询。",
                args_model=tools.ResolvePlaceArgs,
                handler=tools.resolve_place_tool,
                output_hint="返回 matched、selected、candidates；selected 中包含 latitude、longitude、radius_m、address。",
            ),
            ToolDefinition(
                name="query_cracks",
                description="查询裂缝记录，支持按道路或中心点半径、时间范围、严重等级和排序方式筛选。",
                args_model=tools.QueryCracksArgs,
                handler=tools.query_cracks_tool,
                output_hint="返回 items、count 和 message。",
            ),
            ToolDefinition(
                name="query_crack_identities",
                description=(
                    "查询裂缝单体身份档案，支持按道路或中心点半径、时间、生命周期、维修状态、未闭环、复检任务、"
                    "优先级、严重等级和面积增长率筛选。"
                ),
                args_model=tools.QueryCrackIdentitiesArgs,
                handler=tools.query_crack_identities_tool,
                output_hint="返回 items，每条表示一条可跨批次追踪的裂缝身份档案。",
            ),
            ToolDefinition(
                name="get_crack_identity_timeline",
                description="查看指定裂缝身份档案的观测、维修处置和复检时间线。",
                args_model=tools.CrackIdentityArgs,
                handler=tools.get_crack_identity_timeline_tool,
                output_hint="返回 identity 和 timeline。",
            ),
            ToolDefinition(
                name="aggregate_crack_stats",
                description="统计裂缝数量、等级分布、总长度、总面积和宽度信息，支持道路或中心点半径范围。",
                args_model=tools.AggregateCrackStatsArgs,
                handler=tools.aggregate_crack_stats_tool,
                output_hint="返回 total_count、severity_distribution、road_distribution 等统计字段。",
            ),
            ToolDefinition(
                name="compare_crack_stats",
                description="对比两个时间段的裂缝统计情况，支持道路或中心点半径范围。",
                args_model=tools.CompareCrackStatsArgs,
                handler=tools.compare_crack_stats_tool,
                output_hint="返回 current、previous、delta 三组数据。",
            ),
            ToolDefinition(
                name="rank_roads_by_risk",
                description="按综合风险对道路进行排序，识别当前最需要优先关注的道路。",
                args_model=tools.RankRoadsByRiskArgs,
                handler=tools.rank_roads_by_risk_tool,
                output_hint="返回 items 列表，每条包含 road_name、risk_score 等字段。",
            ),
            ToolDefinition(
                name="find_high_risk_cracks",
                description="返回指定道路或中心点半径范围内综合风险最高的裂缝点位列表。",
                args_model=tools.FindHighRiskCracksArgs,
                handler=tools.find_high_risk_cracks_tool,
                output_hint="返回 items、count 和 message。",
            ),
            ToolDefinition(
                name="build_map_geojson",
                description="根据裂缝 ID 生成前端地图可用的 GeoJSON。",
                args_model=tools.CrackIdsArgs,
                handler=tools.build_map_geojson_tool,
                output_hint="返回 FeatureCollection。",
            ),
            ToolDefinition(
                name="get_crack_images",
                description="根据裂缝 ID 返回代表性裂缝图片。",
                args_model=tools.CrackIdsArgs,
                handler=tools.get_crack_images_tool,
                output_hint="返回 images 列表，最多 6 张。",
            ),
            ToolDefinition(
                name="analyze_crack_images",
                description="根据裂缝 ID 读取代表性图片，并调用视觉模型补充裂缝形态判读。",
                args_model=tools.AnalyzeCrackImagesArgs,
                handler=tools.analyze_crack_images_tool,
                output_hint="返回 images_analyzed、summary、findings 等视觉分析结果。",
            ),
            ToolDefinition(
                name="analyze_surrounding_pois",
                description="调用高德周边检索，逐点分析裂缝周边学校、医院、站点等敏感设施，返回 POI 名称、类别和距离。",
                args_model=tools.AnalyzeSurroundingPoisArgs,
                handler=tools.analyze_surrounding_pois_tool,
                output_hint="返回 points、exposure_score、counts、pois；points 中含每个 crack_id 的 nearest_sensitive_poi 和 distance。",
            ),
            ToolDefinition(
                name="generate_maintenance_advice",
                description="根据裂缝统计结果、重点裂缝和周边环境生成带风险评分的维修建议。",
                args_model=tools.GenerateMaintenanceAdviceArgs,
                handler=tools.generate_maintenance_advice_tool,
                output_hint="返回 priority_level、risk_score、summary、actions、reason_factors。",
            ),
        ]
    )
