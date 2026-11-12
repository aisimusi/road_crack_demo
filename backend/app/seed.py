from __future__ import annotations

from sqlalchemy.orm import Session

from app import models

DEFAULT_ROAD_SEGMENTS = [
    {
        "road_name": "中山路",
        "district": "京口区",
        "center_longitude": 119.5129,
        "center_latitude": 32.1988,
        "road_length_km": 2.6,
        "lane_count": 4,
        "remark": "主城区示范巡检道路",
    },
    {
        "road_name": "学府路",
        "district": "京口区",
        "center_longitude": 119.5144,
        "center_latitude": 32.1979,
        "road_length_km": 1.8,
        "lane_count": 4,
        "remark": "高校周边道路",
    },
    {
        "road_name": "解放路",
        "district": "润州区",
        "center_longitude": 119.5162,
        "center_latitude": 32.1995,
        "road_length_km": 3.1,
        "lane_count": 6,
        "remark": "交通干道示范巡检道路",
    },
]


def seed_reference_data(db: Session) -> None:
    for item in DEFAULT_ROAD_SEGMENTS:
        exists = (
            db.query(models.RoadSegment)
            .filter(
                models.RoadSegment.road_name == item["road_name"],
                models.RoadSegment.district == item["district"],
            )
            .first()
        )
        if exists:
            continue
        db.add(models.RoadSegment(**item))
    db.commit()

