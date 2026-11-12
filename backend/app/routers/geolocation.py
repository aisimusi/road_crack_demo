from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app import schemas
from app.services.geolocation import reverse_geocode

router = APIRouter(prefix="/api/geolocation", tags=["geolocation"])


def _resolve_coordinate(primary: float | None, alias: float | None, name: str) -> float:
    value = primary if primary is not None else alias
    if value is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"缺少{name}参数")
    return value


@router.get("/reverse", response_model=schemas.ReverseGeocodeOut)
def reverse_geocode_point(
    latitude: float | None = Query(default=None, ge=-90, le=90, description="纬度，WGS84 或 GCJ02"),
    longitude: float | None = Query(default=None, ge=-180, le=180, description="经度，WGS84 或 GCJ02"),
    lat: float | None = Query(default=None, ge=-90, le=90, description="latitude 的别名"),
    lng: float | None = Query(default=None, ge=-180, le=180, description="longitude 的别名"),
    coordinate_system: str = Query(default="wgs84", pattern="^(wgs84|gcj02|gcj-02|amap|gaode)$"),
) -> schemas.ReverseGeocodeOut:
    resolved_latitude = _resolve_coordinate(latitude, lat, "latitude")
    resolved_longitude = _resolve_coordinate(longitude, lng, "longitude")
    result = reverse_geocode(
        resolved_latitude,
        resolved_longitude,
        coordinate_system=coordinate_system,
        fallback_to_osm=False,
    )
    if not result.road_name:
        detail = result.error_message or result.info or "高德逆地理编码未返回道路名"
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)

    return schemas.ReverseGeocodeOut(
        longitude=resolved_longitude,
        latitude=resolved_latitude,
        coordinate_system=coordinate_system,
        query_longitude=result.query_longitude,
        query_latitude=result.query_latitude,
        road_name=result.road_name,
        district=result.district,
        province=result.province,
        city=result.city,
        adcode=result.adcode,
        township=result.township,
        formatted_address=result.display_name,
        source=result.source,
        info=result.info,
        infocode=result.infocode,
        road_candidates=[schemas.RoadCandidate(**candidate) for candidate in result.road_candidates],
    )
