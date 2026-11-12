from __future__ import annotations

from dataclasses import dataclass
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
from app.database import Base  # noqa: E402


@dataclass(frozen=True)
class FakePlaceCandidate:
    name: str = "江苏大学"
    address: str = "江苏省镇江市京口区学府路301号"
    district: str = "京口区"
    city: str = "镇江市"
    province: str = "江苏省"
    longitude: float = 119.5144
    latitude: float = 32.1979
    type_name: str = "科教文化服务;学校;高等院校"
    distance: float | None = None
    source: str = "test.place_text"


@dataclass(frozen=True)
class FakePoiSummary:
    enabled: bool = True
    source: str = "test"
    radius_m: int = 200
    exposure_score: float = 42.0
    counts: dict[str, int] | None = None
    pois: tuple[dict[str, object], ...] = (
        {
            "category": "学校",
            "name": "测试学校",
            "address": "学府路 1 号",
            "distance": 120.0,
            "longitude": 119.5147,
            "latitude": 32.1982,
            "type_name": "科教文化服务",
            "source": "test",
        },
    )
    error_message: str | None = None


class AgentToolsTestCase(unittest.TestCase):
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
            lane_count=4,
            road_length_km=1.8,
        )
        self.db.add(road)
        self.db.flush()
        self.road = road

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
        self.task = task

        cracks = [
            models.CrackRecord(
                task_id=task.id,
                road_segment_id=road.id,
                crack_code="C001",
                road_name="学府路",
                district="京口区",
                crack_type="linear",
                severity_level=3,
                severity_label="严重",
                severity_score=0.92,
                length_m=3.2,
                avg_width_cm=0.8,
                max_width_cm=1.2,
                area_m2=0.56,
                bbox_x=0,
                bbox_y=0,
                bbox_width=10,
                bbox_height=10,
                longitude=119.5145,
                latitude=32.1980,
                original_image_uri="/uploads/images/a.png",
                result_image_uri="/uploads/results/a.png",
                detected_at=datetime(2026, 6, 22, 9, 0, 0),
            ),
            models.CrackRecord(
                task_id=task.id,
                road_segment_id=road.id,
                crack_code="C002",
                road_name="学府路",
                district="京口区",
                crack_type="block",
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
            ),
        ]
        self.db.add_all(cracks)
        self.db.commit()
        self.cracks = cracks

    def tearDown(self) -> None:
        self.db.close()

    def test_parse_relative_time_range_supports_last_month(self) -> None:
        result = tools.parse_relative_time_range("上个月", base_date=datetime(2026, 6, 23).date())
        self.assertEqual(result["start_date"], "2026-05-01")
        self.assertEqual(result["end_date"], "2026-05-31")

    def test_parse_relative_time_range_supports_explicit_span(self) -> None:
        result = tools.parse_relative_time_range("2026-06-01到2026-06-15")
        self.assertEqual(result["start_date"], "2026-06-01")
        self.assertEqual(result["end_date"], "2026-06-15")

    def test_resolve_query_context_uses_alias(self) -> None:
        result = tools.resolve_query_context_tool(self.db, tools.ResolveQueryContextArgs(query="南门附近最近一周道路情况怎么样"))
        self.assertEqual(result["road_hint"], "南门附近")
        self.assertTrue(result["road_match"]["matched"])
        self.assertEqual(result["road_match"]["road"]["name"], "学府路")

    def test_place_radius_query_uses_resolved_center_not_road_name(self) -> None:
        far_record = models.CrackRecord(
            task_id=self.task.id,
            road_segment_id=self.road.id,
            crack_code="C-FAR",
            road_name="学府路",
            district="京口区",
            crack_type="linear",
            severity_level=3,
            severity_label="严重",
            severity_score=0.88,
            length_m=5.0,
            avg_width_cm=0.8,
            max_width_cm=1.1,
            area_m2=0.70,
            bbox_x=0,
            bbox_y=0,
            bbox_width=10,
            bbox_height=10,
            longitude=119.5260,
            latitude=32.2090,
            original_image_uri="/uploads/images/far.png",
            result_image_uri="/uploads/results/far.png",
            detected_at=datetime(2026, 6, 23, 9, 0, 0),
        )
        self.db.add(far_record)
        self.db.commit()

        original_search_places = tools.search_places
        tools.search_places = lambda keyword, city=None, limit=5: (FakePlaceCandidate(),)
        try:
            context = tools.resolve_query_context_tool(
                self.db,
                tools.ResolveQueryContextArgs(query="江苏大学附近500米严重裂缝有哪些"),
            )
            place = context["place_match"]["selected"]
            result = tools.query_cracks_tool(
                self.db,
                tools.QueryCracksArgs(
                    center_latitude=place["latitude"],
                    center_longitude=place["longitude"],
                    radius_m=place["radius_m"],
                    severity_min=2,
                    order_by="risk_desc",
                    limit=10,
                ),
            )
            stats = tools.aggregate_crack_stats_tool(
                self.db,
                tools.AggregateCrackStatsArgs(
                    center_latitude=place["latitude"],
                    center_longitude=place["longitude"],
                    radius_m=place["radius_m"],
                ),
            )
        finally:
            tools.search_places = original_search_places

        self.assertEqual(context["place_hint"], "江苏大学")
        self.assertEqual(place["radius_m"], 500)
        self.assertEqual(result["count"], 2)
        self.assertNotIn("C-FAR", {item["crack_code"] for item in result["items"]})
        self.assertTrue(all(item["distance_m"] <= 500 for item in result["items"]))
        self.assertEqual(stats["total_count"], 2)
        self.assertEqual(stats["spatial_filter"]["radius_m"], 500)

    def test_find_high_risk_cracks_returns_risk_score(self) -> None:
        result = tools.find_high_risk_cracks_tool(
            self.db,
            tools.FindHighRiskCracksArgs(road_name="学府路", limit=2),
        )
        self.assertEqual(result["count"], 2)
        self.assertGreaterEqual(result["items"][0]["risk_score"], result["items"][1]["risk_score"])
        self.assertIn("reference_pci", result["items"][0])
        self.assertIn("technical_grade", result["items"][0])

    def test_identity_query_and_poi_tools_compose_review_sensitive_filter(self) -> None:
        identity = models.CrackIdentity(
            identity_code="CID-REVIEW-001",
            road_segment_id=self.road.id,
            road_name="学府路",
            district="京口区",
            crack_type="linear",
            lifecycle_status="active",
            maintenance_status="in_progress",
            priority_level="高",
            observation_count=2,
            first_seen_at=datetime(2026, 6, 1, 9, 0, 0),
            last_seen_at=datetime(2026, 6, 20, 9, 0, 0),
            last_task_id=self.task.id,
            center_longitude=119.5145,
            center_latitude=32.1980,
            latest_longitude=119.5146,
            latest_latitude=32.1981,
            current_severity_level=1,
            current_severity_label="轻微",
            current_severity_score=0.4,
            current_length_m=2.0,
            current_avg_width_cm=0.4,
            current_max_width_cm=0.6,
            current_area_m2=0.30,
            max_severity_level=2,
            max_area_m2=0.30,
            growth_area_m2=0.10,
            growth_length_m=0.2,
            latest_original_image_uri="/uploads/images/review.png",
            latest_result_image_uri="/uploads/results/review.png",
        )
        self.db.add(identity)
        self.db.flush()

        review_task = models.InspectionTask(
            task_name="复检任务",
            road_name="学府路",
            district="京口区",
            operator_name="tester",
            task_type="review",
            road_match_status="matched_existing",
            status="finished",
            road_segment_id=self.road.id,
            finished_at=datetime(2026, 6, 20, 10, 0, 0),
        )
        self.db.add(review_task)
        self.db.flush()

        review_record = models.CrackRecord(
            identity_id=identity.id,
            task_id=review_task.id,
            road_segment_id=self.road.id,
            crack_code="R001",
            road_name="学府路",
            district="京口区",
            crack_type="linear",
            severity_level=1,
            severity_label="轻微",
            severity_score=0.4,
            length_m=2.0,
            avg_width_cm=0.4,
            max_width_cm=0.6,
            area_m2=0.30,
            bbox_x=0,
            bbox_y=0,
            bbox_width=10,
            bbox_height=10,
            longitude=119.5146,
            latitude=32.1981,
            original_image_uri="/uploads/images/review.png",
            result_image_uri="/uploads/results/review.png",
            detected_at=datetime(2026, 6, 20, 9, 0, 0),
        )
        self.db.add(review_record)
        self.db.commit()

        original_summarizer = tools.summarize_sensitive_pois
        tools.summarize_sensitive_pois = lambda latitude, longitude, radius_m=300: FakePoiSummary(radius_m=radius_m)
        try:
            result = tools.query_crack_identities_tool(
                self.db,
                tools.QueryCrackIdentitiesArgs(
                    start_date="2026-06-01",
                    end_date="2026-06-30",
                    review_only=True,
                    unclosed_only=True,
                    severity_min=2,
                    area_growth_ratio_min=0.2,
                    severity_growth_logic="or",
                    limit=5,
                ),
            )
            poi_result = tools.analyze_surrounding_pois_tool(
                self.db,
                tools.AnalyzeSurroundingPoisArgs(crack_ids=[review_record.id], radius_m=200),
            )
        finally:
            tools.summarize_sensitive_pois = original_summarizer

        self.assertEqual(result["count"], 1)
        item = result["items"][0]
        self.assertEqual(item["identity_code"], "CID-REVIEW-001")
        self.assertGreater(item["area_growth_ratio"], 0.2)
        self.assertTrue(result["review_only"])
        self.assertTrue(result["unclosed_only"])
        self.assertEqual(poi_result["points"][0]["nearest_sensitive_poi"]["name"], "测试学校")
        self.assertEqual(poi_result["points"][0]["nearest_sensitive_poi"]["distance"], 120.0)

    def test_generate_maintenance_advice_returns_risk_score(self) -> None:
        stats = tools.aggregate_crack_stats_tool(
            self.db,
            tools.AggregateCrackStatsArgs(road_name="学府路"),
        )
        top_cracks = tools.find_high_risk_cracks_tool(
            self.db,
            tools.FindHighRiskCracksArgs(road_name="学府路", limit=2),
        )["items"]
        advice = tools.generate_maintenance_advice_tool(
            self.db,
            tools.GenerateMaintenanceAdviceArgs(stats=stats, top_cracks=top_cracks),
        )
        self.assertIn("risk_score", advice)
        self.assertIn(advice["priority_level"], {"低", "中", "高"})
        self.assertIn(advice["technical_grade"], {"优", "良", "中", "次", "差"})
        self.assertIn(advice["maintenance_level"], {"一级", "二级", "三级", "四级"})
        self.assertIn("max_priority_level", advice)
        self.assertIn("action_candidates", advice)
        self.assertTrue(advice["action_candidates"])
        self.assertTrue(advice["actions"])

    def test_aggregate_stats_include_jtg_reference_fields(self) -> None:
        stats = tools.aggregate_crack_stats_tool(
            self.db,
            tools.AggregateCrackStatsArgs(road_name="学府路"),
        )
        self.assertIn("reference_pci", stats)
        self.assertIn("reference_dr", stats)
        self.assertIn("technical_grade", stats)
        self.assertIn("maintenance_level", stats)
        self.assertLess(stats["reference_pci"], 90)


if __name__ == "__main__":
    unittest.main()
