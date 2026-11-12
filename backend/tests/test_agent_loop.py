from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_BACKEND = Path(__file__).resolve().parents[1]
if str(PROJECT_BACKEND) not in sys.path:
    sys.path.insert(0, str(PROJECT_BACKEND))

from app import models  # noqa: E402
from app.agent import tools  # noqa: E402
from app.agent import agent_loop  # noqa: E402
from app.agent.llm_client import LLMResponse, ToolCallRequest  # noqa: E402
from app.database import Base  # noqa: E402


class LoopingToolLLM:
    mode = "test"

    def generate(self, *, messages, tools_schema, runtime):
        stage = runtime.get("stage")
        if stage == "maintenance_refine":
            return LLMResponse(
                role="assistant",
                content=(
                    '{"priority_level":"中","summary":"按规则建议优先维修。",'
                    '"actions":["优先纳入近期养护计划。"],"reason_factors":["存在中高风险裂缝。"]}'
                ),
            )
        if stage == "final_answer":
            return LLMResponse(role="assistant", content="已基于已有观测完成兜底回答。")
        return LLMResponse(
            role="assistant",
            content="",
            tool_calls=(
                ToolCallRequest(
                    id=f"call-{runtime.get('step')}",
                    name="query_cracks",
                    arguments={"road_name": "学府路", "limit": 1, "order_by": "risk_desc"},
                ),
            ),
        )


class PlanningLLM:
    mode = "test"

    def generate(self, *, messages, tools_schema, runtime):
        stage = runtime.get("stage")
        if stage == "maintenance_refine":
            return LLMResponse(
                role="assistant",
                content=(
                    '{"priority_level":"中","summary":"按候选裂缝和周边敏感点建议优先处置。",'
                    '"actions":["优先复核并纳入近期养护计划。"],"reason_factors":["复检后仍未闭环。"]}'
                ),
            )
        if stage == "final_answer":
            return LLMResponse(role="assistant", content="已通过通用工具链完成复检未闭环敏感点筛选。")

        step = int(runtime.get("step") or 1)
        calls = {
            1: ToolCallRequest(
                id="call-parse",
                name="parse_time_range",
                arguments={"text": "最近一个月"},
            ),
            2: ToolCallRequest(
                id="call-identities",
                name="query_crack_identities",
                arguments={
                    "start_date": "2026-06-01",
                    "end_date": "2026-06-30",
                    "review_only": True,
                    "unclosed_only": True,
                    "severity_min": 2,
                    "area_growth_ratio_min": 0.2,
                    "severity_growth_logic": "or",
                    "limit": 5,
                    "order_by": "priority_desc",
                },
            ),
            3: ToolCallRequest(
                id="call-pois",
                name="analyze_surrounding_pois",
                arguments={"crack_ids": [1], "radius_m": 200, "max_points": 5},
            ),
            4: ToolCallRequest(
                id="call-map",
                name="build_map_geojson",
                arguments={"crack_ids": [1]},
            ),
            5: ToolCallRequest(
                id="call-images",
                name="get_crack_images",
                arguments={"crack_ids": [1]},
            ),
        }
        if step in calls:
            return LLMResponse(role="assistant", content="", tool_calls=(calls[step],))
        return LLMResponse(role="assistant", content="工具链观察已足够。")


class FakePoiSummary:
    enabled = True
    source = "test"
    radius_m = 200
    exposure_score = 40.0
    counts = {"学校": 1, "医院": 0}
    pois = (
        {
            "category": "学校",
            "name": "测试学校",
            "address": "学府路 1 号",
            "distance": 80.0,
            "longitude": 119.5147,
            "latitude": 32.1982,
            "type_name": "科教文化服务",
            "source": "test",
        },
    )
    error_message = None


class AgentLoopTestCase(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        self.db = self.SessionLocal()

        road = models.RoadSegment(
            road_name="学府路",
            district="京口区",
            center_longitude=119.5144,
            center_latitude=32.1979,
        )
        self.db.add(road)
        self.db.flush()

        task = models.InspectionTask(
            task_name="测试任务",
            road_name="学府路",
            district="京口区",
            operator_name="tester",
            status="finished",
            road_segment_id=road.id,
            finished_at=datetime(2026, 6, 22, 10, 0, 0),
        )
        self.db.add(task)
        self.db.flush()

        crack = models.CrackRecord(
            task_id=task.id,
            road_segment_id=road.id,
            crack_code="C001",
            road_name="学府路",
            district="京口区",
            crack_type="linear",
            severity_level=2,
            severity_label="中等",
            severity_score=0.60,
            length_m=1.4,
            avg_width_cm=0.3,
            max_width_cm=0.5,
            area_m2=0.20,
            bbox_x=0,
            bbox_y=0,
            bbox_width=10,
            bbox_height=10,
            longitude=119.5146,
            latitude=32.1981,
            original_image_uri="/uploads/images/b.png",
            result_image_uri="/uploads/results/b.png",
            detected_at=datetime(2026, 6, 20, 9, 0, 0),
        )
        self.db.add(crack)
        self.crack = crack
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()

    def test_max_steps_with_observations_falls_back_instead_of_error(self) -> None:
        original_builder = agent_loop.build_llm_client
        agent_loop.build_llm_client = lambda: LoopingToolLLM()
        try:
            result = agent_loop.run_agent_query(self.db, "查一下学府路风险裂缝")
        finally:
            agent_loop.build_llm_client = original_builder

        self.assertEqual(result["answer"], "已基于已有观测完成兜底回答。")
        self.assertTrue(result["debug"]["fallback_used"])
        self.assertEqual(result["debug"]["fallback_reason"], "max_steps_reached_with_observations")
        self.assertGreaterEqual(len(result["tool_calls"]), agent_loop.MAX_AGENT_STEPS)

    def test_llm_can_compose_general_tools_for_review_sensitive_query(self) -> None:
        identity = models.CrackIdentity(
            identity_code="CID-PLAN-001",
            road_segment_id=self.crack.road_segment_id,
            road_name="学府路",
            district="京口区",
            crack_type="linear",
            lifecycle_status="active",
            maintenance_status="in_progress",
            priority_level="高",
            observation_count=2,
            first_seen_at=datetime(2026, 6, 1, 9, 0, 0),
            last_seen_at=datetime(2026, 6, 20, 9, 0, 0),
            last_task_id=self.crack.task_id,
            center_longitude=119.5146,
            center_latitude=32.1981,
            latest_longitude=119.5146,
            latest_latitude=32.1981,
            current_severity_level=2,
            current_severity_label="中等",
            current_severity_score=0.6,
            current_length_m=1.4,
            current_avg_width_cm=0.3,
            current_max_width_cm=0.5,
            current_area_m2=0.20,
            max_severity_level=2,
            max_area_m2=0.20,
            growth_area_m2=0.05,
            growth_length_m=0.1,
            latest_original_image_uri="/uploads/images/b.png",
            latest_result_image_uri="/uploads/results/b.png",
        )
        self.db.add(identity)
        self.db.flush()
        self.crack.identity_id = identity.id
        review_task = models.InspectionTask(
            task_name="复检任务",
            road_name="学府路",
            district="京口区",
            operator_name="tester",
            task_type="review",
            road_match_status="matched_existing",
            status="finished",
            road_segment_id=self.crack.road_segment_id,
            finished_at=datetime(2026, 6, 20, 10, 0, 0),
        )
        self.db.add(review_task)
        self.db.flush()
        self.crack.task_id = review_task.id
        self.db.commit()

        original_builder = agent_loop.build_llm_client
        original_summarizer = tools.summarize_sensitive_pois
        agent_loop.build_llm_client = lambda: PlanningLLM()
        tools.summarize_sensitive_pois = lambda latitude, longitude, radius_m=300: FakePoiSummary()
        try:
            result = agent_loop.run_agent_query(self.db, "查复检后未闭环且靠近学校医院的裂缝")
        finally:
            agent_loop.build_llm_client = original_builder
            tools.summarize_sensitive_pois = original_summarizer

        tool_names = [call["tool_name"] for call in result["tool_calls"]]
        self.assertIn("query_crack_identities", tool_names)
        self.assertIn("analyze_surrounding_pois", tool_names)
        self.assertIn("build_map_geojson", tool_names)
        self.assertNotIn("find_unclosed_sensitive_review_cracks", tool_names)
        self.assertEqual(result["answer"], "已通过通用工具链完成复检未闭环敏感点筛选。")


if __name__ == "__main__":
    unittest.main()
