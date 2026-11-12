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
from app.database import Base  # noqa: E402
from app.services import crackmamba_detector as detector  # noqa: E402


class IdentityMatchingTestCase(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        self.db = self.SessionLocal()

        self.road = models.RoadSegment(
            road_name="学府路",
            district="京口区",
            center_longitude=119.5144,
            center_latitude=32.1979,
        )
        self.db.add(self.road)
        self.db.flush()

    def tearDown(self) -> None:
        self.db.close()

    def _signature(self, shift: int = 0) -> detector.MaskSignature:
        bitmap = detector.np.zeros((64, 64), dtype=bool)
        bitmap[16 + shift : 48 + shift, 26:38] = True
        return detector.MaskSignature(
            bbox={"x": 20, "y": 10, "width": 16, "height": 40},
            area_px=int(bitmap.sum()),
            centroid_x=28.0,
            centroid_y=30.0 + shift,
            orientation_deg=90.0,
            aspect_ratio=2.5,
            shape_bitmap=bitmap,
        )

    def _record(self, embedding: list[float], longitude: float, latitude: float) -> detector.DetectionRecord:
        metrics = {
            "crack_type": "longitudinal_crack",
            "severity_level": 2,
            "severity_label": "中等",
            "severity_score": 0.5,
            "length_m": 2.0,
            "avg_width_cm": 0.4,
            "max_width_cm": 0.6,
            "area_m2": 0.02,
            "bbox": {"x": 20, "y": 10, "width": 16, "height": 40},
            "embedding": embedding,
        }
        return detector.DetectionRecord(
            record_id=1,
            frame=detector.FrameMeta(
                frame_path=Path("/tmp/fake.png"),
                stem="fake",
                elapsed_seconds=0.0,
                srt=detector.SrtEntry(
                    index=1,
                    start_seconds=0.0,
                    end_seconds=0.5,
                    captured_at=datetime(2026, 7, 1, 10, 0, 0),
                    latitude=latitude,
                    longitude=longitude,
                    rel_alt=None,
                    abs_alt=None,
                    focal_len=None,
                    dzoom_ratio=None,
                    frame_count=None,
                    yaw=None,
                    pitch=None,
                    roll=None,
                ),
            ),
            frame_path=Path("/tmp/fake.png"),
            mask_path=Path("/tmp/fake_mask.png"),
            overlay_path=Path("/tmp/fake_overlay.png"),
            metrics=metrics,
            mask_signature=self._signature(),
            longitude=longitude,
            latitude=latitude,
            detected_at=datetime(2026, 7, 1, 10, 0, 0),
        )

    def test_embedding_can_match_when_same_district_and_geo_is_relaxed(self) -> None:
        identity = models.CrackIdentity(
            identity_code="CID-000001",
            road_segment_id=self.road.id,
            road_name="另一条路",
            district="京口区",
            crack_type="longitudinal_crack",
            center_longitude=119.5144,
            center_latitude=32.1979,
            latest_longitude=119.51445,
            latest_latitude=32.19795,
            current_severity_level=2,
            current_severity_label="中等",
            current_severity_score=0.5,
            current_length_m=2.0,
            current_avg_width_cm=0.4,
            current_max_width_cm=0.6,
            current_area_m2=0.02,
            max_severity_level=2,
            max_area_m2=0.02,
            embedding_model="efficientnet_penultimate",
            embedding_json="[1.0,0.0,0.0]",
            embedding_count=1,
            feature_json=detector.json.dumps(detector._signature_to_feature_dict(self._signature()), ensure_ascii=False),
        )
        self.db.add(identity)
        self.db.commit()

        record = self._record([0.99, 0.01, 0.0], 119.51446, 32.19796)
        matched, details = detector._find_matching_identity(self.db, record, self.road)
        self.assertIsNotNone(matched)
        self.assertEqual(matched.id, identity.id)
        self.assertIsNotNone(details)
        self.assertGreater(details["embedding_similarity"], 0.8)

    def test_margin_rejects_ambiguous_embedding_match(self) -> None:
        identity_a = models.CrackIdentity(
            identity_code="CID-000001",
            road_segment_id=self.road.id,
            road_name="学府路",
            district="京口区",
            crack_type="longitudinal_crack",
            center_longitude=119.5144,
            center_latitude=32.1979,
            latest_longitude=119.51445,
            latest_latitude=32.19795,
            current_severity_level=2,
            current_severity_label="中等",
            current_severity_score=0.5,
            current_length_m=2.0,
            current_avg_width_cm=0.4,
            current_max_width_cm=0.6,
            current_area_m2=0.02,
            max_severity_level=2,
            max_area_m2=0.02,
            embedding_model="efficientnet_penultimate",
            embedding_json="[1.0,0.0,0.0]",
            embedding_count=1,
        )
        identity_b = models.CrackIdentity(
            identity_code="CID-000002",
            road_segment_id=self.road.id,
            road_name="学府路",
            district="京口区",
            crack_type="longitudinal_crack",
            center_longitude=119.5144,
            center_latitude=32.1979,
            latest_longitude=119.51447,
            latest_latitude=32.19797,
            current_severity_level=2,
            current_severity_label="中等",
            current_severity_score=0.5,
            current_length_m=2.0,
            current_avg_width_cm=0.4,
            current_max_width_cm=0.6,
            current_area_m2=0.02,
            max_severity_level=2,
            max_area_m2=0.02,
            embedding_model="efficientnet_penultimate",
            embedding_json="[0.98,0.02,0.0]",
            embedding_count=1,
        )
        self.db.add_all([identity_a, identity_b])
        self.db.commit()

        record = self._record([0.99, 0.01, 0.0], 119.51446, 32.19796)
        matched, details = detector._find_matching_identity(self.db, record, self.road)
        self.assertIsNone(matched)
        self.assertIsNotNone(details)
        self.assertLess(details["margin"], detector.CLASSIFIER_EMBEDDING_MARGIN_THRESHOLD)


if __name__ == "__main__":
    unittest.main()
