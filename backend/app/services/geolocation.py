from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy.orm import Session

from app import models
from app.services.srt_parser import SrtCoordinateSummary, parse_srt_file, summarize_srt_coordinates

PENDING_ROAD_NAME = "待导入SRT定位"
PENDING_DISTRICT = "待导入SRT定位"
UNKNOWN_DISTRICT = "未知区域"
COORDINATE_ROAD_NAME_PREFIX = "经纬度定位道路("
ROAD_SEGMENT_MATCH_DISTANCE_M = 120.0
REVIEW_TASK_TYPES = {"review", "reinspection"}
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
AMAP_REVERSE_URL = "https://restapi.amap.com/v3/geocode/regeo"
AMAP_PLACE_TEXT_URL = "https://restapi.amap.com/v3/place/text"
AMAP_PLACE_AROUND_URL = "https://restapi.amap.com/v3/place/around"
AMAP_KEY_ENV_NAMES = ("AMAP_WEB_SERVICE_KEY", "GAODE_WEB_SERVICE_KEY", "AMAP_KEY")

SENSITIVE_POI_CATEGORIES = {
    "school": {"label": "学校", "keyword": "学校", "weight": 18},
    "hospital": {"label": "医院", "keyword": "医院", "weight": 16},
    "transit": {"label": "交通站点", "keyword": "公交站", "weight": 10},
    "metro": {"label": "地铁站", "keyword": "地铁站", "weight": 12},
    "campus_gate": {"label": "校门", "keyword": "校门", "weight": 9},
    "library": {"label": "图书馆", "keyword": "图书馆", "weight": 8},
}

GCJ02_AXIS = 6_378_245.0
GCJ02_EE = 0.006693421622965943


@dataclass(frozen=True)
class TaskLocation:
    road_name: str
    district: str
    summary: SrtCoordinateSummary
    source: str
    display_name: str | None = None


@dataclass(frozen=True)
class ReverseGeocodeResult:
    road_name: str | None
    district: str | None
    display_name: str | None
    source: str
    longitude: float | None = None
    latitude: float | None = None
    query_longitude: float | None = None
    query_latitude: float | None = None
    province: str | None = None
    city: str | None = None
    adcode: str | None = None
    township: str | None = None
    road_candidates: tuple[dict[str, object], ...] = ()
    info: str | None = None
    infocode: str | None = None
    error_message: str | None = None

    @property
    def has_location(self) -> bool:
        return bool(self.road_name or self.district)


@dataclass(frozen=True)
class PlaceCandidate:
    name: str
    address: str | None
    district: str | None
    city: str | None
    province: str | None
    longitude: float | None
    latitude: float | None
    type_name: str | None
    distance: float | None
    source: str


@dataclass(frozen=True)
class SensitivePoiSummary:
    enabled: bool
    source: str
    radius_m: int
    exposure_score: float
    counts: dict[str, int]
    pois: tuple[dict[str, object], ...]
    error_message: str | None = None


def is_pending_location(road_name: str | None, district: str | None) -> bool:
    return not road_name or not district or road_name == PENDING_ROAD_NAME or district == PENDING_DISTRICT


def is_coordinate_location(road_name: str | None) -> bool:
    return bool(road_name and road_name.startswith(COORDINATE_ROAD_NAME_PREFIX))


def is_review_task_type(task_type: str | None) -> bool:
    return (task_type or "").strip() in REVIEW_TASK_TYPES


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _first_text(mapping: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = _clean_text(mapping.get(key))
        if value:
            return value
    return None


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _dict_items(value: object) -> list[dict]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _amap_items(value: object, nested_key: str) -> list[dict]:
    if isinstance(value, dict) and nested_key in value:
        return _dict_items(value.get(nested_key))
    return _dict_items(value)


def _to_float(value: object) -> float | None:
    text = _clean_text(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _amap_key() -> str | None:
    for env_name in AMAP_KEY_ENV_NAMES:
        key = _clean_text(os.getenv(env_name))
        if key:
            return key
    return None


def _request_amap_json(url: str, params: dict[str, object], *, timeout: float = 3.0) -> dict | None:
    key = _amap_key()
    if not key:
        return None

    query = urlencode(
        {
            "key": key,
            "output": "JSON",
            **params,
        }
    )
    request = Request(
        f"{url}?{query}",
        headers={"User-Agent": "road-crack-demo/1.0"},
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else None


def _out_of_china(longitude: float, latitude: float) -> bool:
    return not (72.004 <= longitude <= 137.8347 and 0.8293 <= latitude <= 55.8271)


def _transform_latitude(longitude_offset: float, latitude_offset: float) -> float:
    result = -100.0 + 2.0 * longitude_offset + 3.0 * latitude_offset + 0.2 * latitude_offset * latitude_offset
    result += 0.1 * longitude_offset * latitude_offset + 0.2 * math.sqrt(abs(longitude_offset))
    result += (20.0 * math.sin(6.0 * longitude_offset * math.pi) + 20.0 * math.sin(2.0 * longitude_offset * math.pi)) * 2.0 / 3.0
    result += (20.0 * math.sin(latitude_offset * math.pi) + 40.0 * math.sin(latitude_offset / 3.0 * math.pi)) * 2.0 / 3.0
    result += (160.0 * math.sin(latitude_offset / 12.0 * math.pi) + 320 * math.sin(latitude_offset * math.pi / 30.0)) * 2.0 / 3.0
    return result


def _transform_longitude(longitude_offset: float, latitude_offset: float) -> float:
    result = 300.0 + longitude_offset + 2.0 * latitude_offset + 0.1 * longitude_offset * longitude_offset
    result += 0.1 * longitude_offset * latitude_offset + 0.1 * math.sqrt(abs(longitude_offset))
    result += (20.0 * math.sin(6.0 * longitude_offset * math.pi) + 20.0 * math.sin(2.0 * longitude_offset * math.pi)) * 2.0 / 3.0
    result += (20.0 * math.sin(longitude_offset * math.pi) + 40.0 * math.sin(longitude_offset / 3.0 * math.pi)) * 2.0 / 3.0
    result += (150.0 * math.sin(longitude_offset / 12.0 * math.pi) + 300.0 * math.sin(longitude_offset / 30.0 * math.pi)) * 2.0 / 3.0
    return result


def _wgs84_to_gcj02(longitude: float, latitude: float) -> tuple[float, float]:
    if _out_of_china(longitude, latitude):
        return longitude, latitude

    longitude_offset = longitude - 105.0
    latitude_offset = latitude - 35.0
    delta_latitude = _transform_latitude(longitude_offset, latitude_offset)
    delta_longitude = _transform_longitude(longitude_offset, latitude_offset)
    rad_latitude = latitude / 180.0 * math.pi
    magic = math.sin(rad_latitude)
    magic = 1 - GCJ02_EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    delta_latitude = (delta_latitude * 180.0) / ((GCJ02_AXIS * (1 - GCJ02_EE)) / (magic * sqrt_magic) * math.pi)
    delta_longitude = (delta_longitude * 180.0) / (GCJ02_AXIS / sqrt_magic * math.cos(rad_latitude) * math.pi)
    return longitude + delta_longitude, latitude + delta_latitude


def _distance_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    lat_scale = 111_320.0
    lon_scale = 111_320.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lon1 - lon2) * lon_scale, (lat1 - lat2) * lat_scale)


def _lon_lat_to_local_xy(
    longitude: float,
    latitude: float,
    origin_longitude: float,
    origin_latitude: float,
) -> tuple[float, float]:
    lat_scale = 111_320.0
    lon_scale = 111_320.0 * math.cos(math.radians(origin_latitude))
    return (longitude - origin_longitude) * lon_scale, (latitude - origin_latitude) * lat_scale


def _point_to_segment_distance_m(
    point_longitude: float,
    point_latitude: float,
    start_longitude: float,
    start_latitude: float,
    end_longitude: float,
    end_latitude: float,
) -> float:
    px, py = _lon_lat_to_local_xy(point_longitude, point_latitude, point_longitude, point_latitude)
    sx, sy = _lon_lat_to_local_xy(start_longitude, start_latitude, point_longitude, point_latitude)
    ex, ey = _lon_lat_to_local_xy(end_longitude, end_latitude, point_longitude, point_latitude)
    dx = ex - sx
    dy = ey - sy
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-9:
        return math.hypot(px - sx, py - sy)
    t = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / length_sq))
    nearest_x = sx + t * dx
    nearest_y = sy + t * dy
    return math.hypot(px - nearest_x, py - nearest_y)


def _segment_match_distance(segment: models.RoadSegment, summary: SrtCoordinateSummary) -> float:
    distances: list[float] = []
    if segment.center_longitude is not None and segment.center_latitude is not None:
        distances.append(
            _distance_m(
                float(segment.center_longitude),
                float(segment.center_latitude),
                summary.center_longitude,
                summary.center_latitude,
            )
        )

    has_segment_endpoints = all(
        value is not None
        for value in (
            segment.start_longitude,
            segment.start_latitude,
            segment.end_longitude,
            segment.end_latitude,
        )
    )
    if has_segment_endpoints:
        start_longitude = float(segment.start_longitude)
        start_latitude = float(segment.start_latitude)
        end_longitude = float(segment.end_longitude)
        end_latitude = float(segment.end_latitude)
        distances.append(
            _point_to_segment_distance_m(
                summary.center_longitude,
                summary.center_latitude,
                start_longitude,
                start_latitude,
                end_longitude,
                end_latitude,
            )
        )
        forward_distance = (
            _distance_m(start_longitude, start_latitude, summary.start_longitude, summary.start_latitude)
            + _distance_m(end_longitude, end_latitude, summary.end_longitude, summary.end_latitude)
        ) / 2
        reverse_distance = (
            _distance_m(start_longitude, start_latitude, summary.end_longitude, summary.end_latitude)
            + _distance_m(end_longitude, end_latitude, summary.start_longitude, summary.start_latitude)
        ) / 2
        distances.append(min(forward_distance, reverse_distance))

    return min(distances) if distances else float("inf")


def find_matching_road_segment_by_summary(
    db: Session,
    summary: SrtCoordinateSummary,
    *,
    exclude_segment_ids: set[int] | None = None,
    max_distance_m: float = ROAD_SEGMENT_MATCH_DISTANCE_M,
) -> tuple[models.RoadSegment | None, float | None]:
    excluded = exclude_segment_ids or set()
    candidates = db.query(models.RoadSegment).all()
    best_segment: models.RoadSegment | None = None
    best_distance = float("inf")
    for segment in candidates:
        if segment.id in excluded:
            continue
        distance = _segment_match_distance(segment, summary)
        if distance < best_distance:
            best_segment = segment
            best_distance = distance

    if best_segment is None or best_distance > max_distance_m:
        return None, None
    return best_segment, best_distance


def _summarize_srt_paths(srt_paths: Iterable[Path]) -> list[tuple[Path, SrtCoordinateSummary]]:
    summaries: list[tuple[Path, SrtCoordinateSummary]] = []
    for srt_path in srt_paths:
        summaries.append((srt_path, summarize_srt_coordinates(parse_srt_file(srt_path))))
    return summaries


def find_matching_road_segment_from_srt_paths(
    db: Session,
    srt_paths: Iterable[Path],
    *,
    exclude_segment_ids: set[int] | None = None,
) -> tuple[models.RoadSegment | None, SrtCoordinateSummary | None, float | None]:
    best_segment: models.RoadSegment | None = None
    best_summary: SrtCoordinateSummary | None = None
    best_distance: float | None = None
    for _, summary in _summarize_srt_paths(srt_paths):
        segment, distance = find_matching_road_segment_by_summary(
            db,
            summary,
            exclude_segment_ids=exclude_segment_ids,
        )
        if segment is None or distance is None:
            continue
        if best_distance is None or distance < best_distance:
            best_segment = segment
            best_summary = summary
            best_distance = distance
    return best_segment, best_summary, best_distance


def _pick_amap_road_candidates(regeocode: dict, address_component: dict) -> tuple[dict[str, object], ...]:
    candidates: list[dict[str, object]] = []

    street_number = _as_dict(address_component.get("streetNumber"))
    street = _clean_text(street_number.get("street"))
    if street:
        candidates.append(
            {
                "name": street,
                "distance": _to_float(street_number.get("distance")),
                "direction": _clean_text(street_number.get("direction")),
                "source": "streetNumber",
            }
        )

    for road in _amap_items(regeocode.get("roads"), "road"):
        name = _clean_text(road.get("name"))
        if name:
            candidates.append(
                {
                    "name": name,
                    "distance": _to_float(road.get("distance")),
                    "direction": _clean_text(road.get("direction")),
                    "source": "roads",
                    "id": _clean_text(road.get("id")),
                }
            )

    for road_inter in _amap_items(regeocode.get("roadinters"), "roadinter"):
        distance = _to_float(road_inter.get("distance"))
        for key in ("first_name", "second_name"):
            name = _clean_text(road_inter.get(key))
            if name:
                candidates.append(
                    {
                        "name": name,
                        "distance": distance,
                        "direction": _clean_text(road_inter.get("direction")),
                        "source": f"roadinters.{key}",
                        "id": _clean_text(road_inter.get(key.replace("_name", "_id"))),
                    }
                )

    if not candidates:
        return ()
    candidates.sort(
        key=lambda item: (
            item.get("distance") is None,
            float(item["distance"]) if item.get("distance") is not None else float("inf"),
        )
    )
    deduped: list[dict[str, object]] = []
    seen_names: set[str] = set()
    for candidate in candidates:
        name = str(candidate["name"])
        if name in seen_names:
            continue
        seen_names.add(name)
        deduped.append(candidate)
    return tuple(deduped)


def _pick_amap_road_name(regeocode: dict, address_component: dict) -> str | None:
    candidates = _pick_amap_road_candidates(regeocode, address_component)
    if not candidates:
        return None
    return str(candidates[0]["name"])


def _reverse_geocode_amap(
    latitude: float,
    longitude: float,
    *,
    coordinate_system: str = "wgs84",
) -> ReverseGeocodeResult:
    key = _amap_key()
    if not key:
        return ReverseGeocodeResult(
            None,
            None,
            None,
            "amap",
            longitude=longitude,
            latitude=latitude,
            error_message="未配置高德 Web 服务 Key，请设置 AMAP_WEB_SERVICE_KEY",
        )

    normalized_system = coordinate_system.lower()
    if normalized_system in {"gcj02", "gcj-02", "amap", "gaode"}:
        amap_longitude, amap_latitude = longitude, latitude
    else:
        amap_longitude, amap_latitude = _wgs84_to_gcj02(longitude, latitude)
    try:
        payload = _request_amap_json(
            AMAP_REVERSE_URL,
            {
                "location": f"{amap_longitude:.6f},{amap_latitude:.6f}",
                "radius": "1000",
                "extensions": "all",
                "roadlevel": "0",
            },
        )
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return ReverseGeocodeResult(
            None,
            None,
            None,
            "amap",
            longitude=longitude,
            latitude=latitude,
            query_longitude=amap_longitude,
            query_latitude=amap_latitude,
            error_message=str(exc),
        )

    if not isinstance(payload, dict) or payload.get("status") != "1":
        return ReverseGeocodeResult(
            None,
            None,
            None,
            "amap",
            longitude=longitude,
            latitude=latitude,
            query_longitude=amap_longitude,
            query_latitude=amap_latitude,
            info=_clean_text(payload.get("info")) if isinstance(payload, dict) else None,
            infocode=_clean_text(payload.get("infocode")) if isinstance(payload, dict) else None,
            error_message=_clean_text(payload.get("info")) if isinstance(payload, dict) else "高德逆地理编码返回异常",
        )

    regeocode = _as_dict(payload.get("regeocode"))
    address_component = _as_dict(regeocode.get("addressComponent"))
    road_candidates = _pick_amap_road_candidates(regeocode, address_component)
    road_name = str(road_candidates[0]["name"]) if road_candidates else None
    district = _first_text(address_component, ("district", "township", "city", "province"))
    display_name = _clean_text(regeocode.get("formatted_address"))
    return ReverseGeocodeResult(
        road_name,
        district,
        display_name,
        "amap",
        longitude=longitude,
        latitude=latitude,
        query_longitude=amap_longitude,
        query_latitude=amap_latitude,
        province=_clean_text(address_component.get("province")),
        city=_clean_text(address_component.get("city")),
        adcode=_clean_text(address_component.get("adcode")),
        township=_clean_text(address_component.get("township")),
        road_candidates=road_candidates,
        info=_clean_text(payload.get("info")),
        infocode=_clean_text(payload.get("infocode")),
    )


def _parse_place_candidate(poi: dict, *, source: str) -> PlaceCandidate | None:
    name = _clean_text(poi.get("name"))
    if not name:
        return None

    location_text = _clean_text(poi.get("location"))
    longitude = None
    latitude = None
    if location_text and "," in location_text:
        longitude_text, latitude_text = location_text.split(",", 1)
        longitude = _to_float(longitude_text)
        latitude = _to_float(latitude_text)

    return PlaceCandidate(
        name=name,
        address=_clean_text(poi.get("address")),
        district=_clean_text(poi.get("adname")) or _clean_text(poi.get("district")),
        city=_clean_text(poi.get("cityname")) or _clean_text(poi.get("city")),
        province=_clean_text(poi.get("pname")) or _clean_text(poi.get("province")),
        longitude=longitude,
        latitude=latitude,
        type_name=_clean_text(poi.get("type")),
        distance=_to_float(poi.get("distance")),
        source=source,
    )


def search_places(keyword: str, *, city: str | None = None, limit: int = 5) -> tuple[PlaceCandidate, ...]:
    normalized = _clean_text(keyword)
    if not normalized:
        return ()

    try:
        payload = _request_amap_json(
            AMAP_PLACE_TEXT_URL,
            {
                "keywords": normalized,
                "offset": str(max(1, min(limit, 20))),
                "page": "1",
                "extensions": "all",
                "city": city or "",
                "citylimit": "true" if city else "false",
            },
        )
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
        return ()

    if not isinstance(payload, dict) or payload.get("status") != "1":
        return ()

    candidates: list[PlaceCandidate] = []
    for poi in payload.get("pois") or []:
        if not isinstance(poi, dict):
            continue
        candidate = _parse_place_candidate(poi, source="amap.place_text")
        if candidate:
            candidates.append(candidate)
    return tuple(candidates)


def search_places_around(
    latitude: float,
    longitude: float,
    *,
    keyword: str,
    radius_m: int = 500,
    limit: int = 10,
    coordinate_system: str = "wgs84",
) -> tuple[PlaceCandidate, ...]:
    normalized_keyword = _clean_text(keyword)
    if not normalized_keyword:
        return ()

    normalized_system = coordinate_system.lower()
    if normalized_system in {"gcj02", "gcj-02", "amap", "gaode"}:
        amap_longitude, amap_latitude = longitude, latitude
    else:
        amap_longitude, amap_latitude = _wgs84_to_gcj02(longitude, latitude)

    try:
        payload = _request_amap_json(
            AMAP_PLACE_AROUND_URL,
            {
                "location": f"{amap_longitude:.6f},{amap_latitude:.6f}",
                "keywords": normalized_keyword,
                "radius": str(max(50, min(radius_m, 5000))),
                "sortrule": "distance",
                "offset": str(max(1, min(limit, 20))),
                "page": "1",
                "extensions": "all",
            },
        )
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
        return ()

    if not isinstance(payload, dict) or payload.get("status") != "1":
        return ()

    candidates: list[PlaceCandidate] = []
    for poi in payload.get("pois") or []:
        if not isinstance(poi, dict):
            continue
        candidate = _parse_place_candidate(poi, source="amap.place_around")
        if candidate:
            candidates.append(candidate)
    return tuple(candidates)


def summarize_sensitive_pois(
    latitude: float,
    longitude: float,
    *,
    radius_m: int = 300,
    limit: int = 8,
    coordinate_system: str = "wgs84",
) -> SensitivePoiSummary:
    if not _amap_key():
        return SensitivePoiSummary(
            enabled=False,
            source="disabled",
            radius_m=radius_m,
            exposure_score=0.0,
            counts={meta["label"]: 0 for meta in SENSITIVE_POI_CATEGORIES.values()},
            pois=(),
            error_message="未配置高德 Web 服务 Key",
        )

    counts: dict[str, int] = {}
    score = 0.0
    collected: list[dict[str, object]] = []
    seen_names: set[str] = set()

    for category_key, meta in SENSITIVE_POI_CATEGORIES.items():
        category_pois = search_places_around(
            latitude,
            longitude,
            keyword=str(meta["keyword"]),
            radius_m=radius_m,
            limit=limit,
            coordinate_system=coordinate_system,
        )
        label = str(meta["label"])
        counts[label] = len(category_pois)
        score += min(len(category_pois), 3) * float(meta["weight"])
        for poi in category_pois[:2]:
            if poi.name in seen_names:
                continue
            seen_names.add(poi.name)
            collected.append(
                {
                    "category": label,
                    "name": poi.name,
                    "address": poi.address,
                    "distance": poi.distance,
                    "longitude": poi.longitude,
                    "latitude": poi.latitude,
                    "type_name": poi.type_name,
                    "source": poi.source,
                }
            )

    collected.sort(
        key=lambda item: (
            item.get("distance") is None,
            float(item["distance"]) if item.get("distance") is not None else float("inf"),
        )
    )
    return SensitivePoiSummary(
        enabled=True,
        source="amap",
        radius_m=radius_m,
        exposure_score=round(min(score, 100.0), 1),
        counts=counts,
        pois=tuple(collected[:limit]),
    )


def _reverse_geocode_osm(latitude: float, longitude: float) -> ReverseGeocodeResult:
    query = urlencode(
        {
            "format": "jsonv2",
            "lat": f"{latitude:.7f}",
            "lon": f"{longitude:.7f}",
            "zoom": "18",
            "addressdetails": "1",
            "accept-language": "zh-CN,zh,en",
        }
    )
    request = Request(
        f"{NOMINATIM_REVERSE_URL}?{query}",
        headers={"User-Agent": "road-crack-demo/1.0"},
    )
    try:
        with urlopen(request, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
        return ReverseGeocodeResult(None, None, None, "openstreetmap")

    address = payload.get("address") if isinstance(payload, dict) else {}
    if not isinstance(address, dict):
        address = {}

    road_name = _first_text(
        address,
        (
            "road",
            "pedestrian",
            "footway",
            "path",
            "cycleway",
            "residential",
            "neighbourhood",
            "suburb",
            "village",
        ),
    )
    district = _first_text(
        address,
        (
            "city_district",
            "district",
            "county",
            "state_district",
            "suburb",
            "city",
            "town",
            "village",
        ),
    )
    display_name = _clean_text(payload.get("display_name"))
    return ReverseGeocodeResult(
        road_name,
        district,
        display_name,
        "openstreetmap",
        longitude=longitude,
        latitude=latitude,
    )


def _merge_reverse_geocode_results(results: list[ReverseGeocodeResult]) -> ReverseGeocodeResult:
    road_name: str | None = None
    district: str | None = None
    display_name: str | None = None
    longitude: float | None = None
    latitude: float | None = None
    query_longitude: float | None = None
    query_latitude: float | None = None
    province: str | None = None
    city: str | None = None
    adcode: str | None = None
    township: str | None = None
    road_candidates: tuple[dict[str, object], ...] = ()
    info: str | None = None
    infocode: str | None = None
    error_message: str | None = None
    used_sources: list[str] = []

    for result in results:
        used = False
        if not road_name and result.road_name:
            road_name = result.road_name
            used = True
        if not district and result.district:
            district = result.district
            used = True
        if not display_name and result.display_name:
            display_name = result.display_name
            used = True
        if longitude is None:
            longitude = result.longitude
        if latitude is None:
            latitude = result.latitude
        if query_longitude is None:
            query_longitude = result.query_longitude
        if query_latitude is None:
            query_latitude = result.query_latitude
        if not province and result.province:
            province = result.province
        if not city and result.city:
            city = result.city
        if not adcode and result.adcode:
            adcode = result.adcode
        if not township and result.township:
            township = result.township
        if not road_candidates and result.road_candidates:
            road_candidates = result.road_candidates
        if not info and result.info:
            info = result.info
        if not infocode and result.infocode:
            infocode = result.infocode
        if not error_message and result.error_message:
            error_message = result.error_message
        if used and result.source not in used_sources:
            used_sources.append(result.source)
        if road_name and district:
            break

    return ReverseGeocodeResult(
        road_name,
        district,
        display_name,
        "+".join(used_sources) or "none",
        longitude=longitude,
        latitude=latitude,
        query_longitude=query_longitude,
        query_latitude=query_latitude,
        province=province,
        city=city,
        adcode=adcode,
        township=township,
        road_candidates=road_candidates,
        info=info,
        infocode=infocode,
        error_message=error_message,
    )


def reverse_geocode(
    latitude: float,
    longitude: float,
    *,
    coordinate_system: str = "wgs84",
    fallback_to_osm: bool = True,
) -> ReverseGeocodeResult:
    results = [_reverse_geocode_amap(latitude, longitude, coordinate_system=coordinate_system)]
    if not results[0].road_name or not results[0].district:
        if fallback_to_osm:
            results.append(_reverse_geocode_osm(latitude, longitude))
    return _merge_reverse_geocode_results(results)


def _coordinate_road_name(summary: SrtCoordinateSummary) -> str:
    return f"经纬度定位道路({summary.center_longitude:.5f},{summary.center_latitude:.5f})"


def _get_or_create_road_segment(
    db: Session,
    road_name: str,
    district: str,
    summary: SrtCoordinateSummary,
    source: str,
) -> models.RoadSegment:
    segment = (
        db.query(models.RoadSegment)
        .filter(models.RoadSegment.road_name == road_name, models.RoadSegment.district == district)
        .first()
    )
    if not segment:
        segment = models.RoadSegment(
            road_name=road_name,
            district=district,
            remark=f"由 SRT 经纬度通过地图自动定位（{source}）",
        )
        db.add(segment)
        db.flush()

    segment.center_longitude = summary.center_longitude
    segment.center_latitude = summary.center_latitude
    segment.start_longitude = summary.start_longitude
    segment.start_latitude = summary.start_latitude
    segment.end_longitude = summary.end_longitude
    segment.end_latitude = summary.end_latitude
    return segment


def _update_road_segment_from_summary(segment: models.RoadSegment, summary: SrtCoordinateSummary) -> None:
    segment.center_longitude = summary.center_longitude
    segment.center_latitude = summary.center_latitude
    segment.start_longitude = summary.start_longitude
    segment.start_latitude = summary.start_latitude
    segment.end_longitude = summary.end_longitude
    segment.end_latitude = summary.end_latitude


def locate_srt_file(db: Session, srt_path: Path) -> TaskLocation:
    summary = summarize_srt_coordinates(parse_srt_file(srt_path))
    geocode = reverse_geocode(summary.center_latitude, summary.center_longitude)

    road_name = (geocode.road_name or _coordinate_road_name(summary))[:64]
    district = (geocode.district or UNKNOWN_DISTRICT)[:64]
    source = geocode.source if geocode.road_name else "coordinates"
    return TaskLocation(
        road_name=road_name,
        district=district,
        summary=summary,
        source=source,
        display_name=geocode.display_name,
    )


def apply_task_location(
    db: Session,
    task: models.InspectionTask,
    location: TaskLocation,
    *,
    matched_segment: models.RoadSegment | None = None,
    road_match_status: str | None = None,
    create_segment: bool = True,
) -> TaskLocation:
    if matched_segment is not None:
        segment = matched_segment
        _update_road_segment_from_summary(segment, location.summary)
    elif create_segment:
        segment = _get_or_create_road_segment(db, location.road_name, location.district, location.summary, location.source)
    else:
        segment = None
    task.road_name = location.road_name
    task.district = location.district
    task.road_segment_id = segment.id if segment is not None else None
    if road_match_status:
        task.road_match_status = road_match_status
    elif is_review_task_type(task.task_type):
        task.road_match_status = "matched_existing" if matched_segment is not None else "unmatched"
    else:
        task.road_match_status = "not_required"
    if task.status == "pending":
        if is_review_task_type(task.task_type) and task.road_match_status == "matched_existing":
            task.progress_message = "复检路段已通过 SRT 经纬度匹配到系统已有路段"
        elif is_review_task_type(task.task_type):
            task.progress_message = "复检任务未匹配到系统已有路段，仅保存检测结果"
        elif location.source == "coordinates":
            task.progress_message = "地图未返回道路名，已保留经纬度定位结果"
        else:
            task.progress_message = "已根据 SRT 经纬度从地图定位道路"
    db.flush()
    return location


def apply_task_location_from_srt(db: Session, task: models.InspectionTask, srt_path: Path) -> TaskLocation:
    return apply_task_location_from_srt_paths(db, task, [srt_path])


def locate_best_srt_location(db: Session, srt_paths: Iterable[Path]) -> TaskLocation:
    locations: list[TaskLocation] = []
    for srt_path in srt_paths:
        locations.append(locate_srt_file(db, srt_path))

    if not locations:
        raise ValueError("未找到可用于定位的 SRT 文件")

    for location in locations:
        if location.source != "coordinates":
            return location
    return locations[0]


def apply_task_location_from_srt_paths(
    db: Session,
    task: models.InspectionTask,
    srt_paths: Iterable[Path],
) -> TaskLocation:
    paths = list(srt_paths)
    if is_review_task_type(task.task_type):
        exclude_segment_ids: set[int] = set()
        if task.road_segment_id and task.road_match_status == "unmatched":
            exclude_segment_ids.add(int(task.road_segment_id))
        matched_segment, matched_summary, _ = find_matching_road_segment_from_srt_paths(
            db,
            paths,
            exclude_segment_ids=exclude_segment_ids,
        )
        if matched_segment is not None and matched_summary is not None:
            return apply_task_location(
                db,
                task,
                TaskLocation(
                    road_name=matched_segment.road_name,
                    district=matched_segment.district,
                    summary=matched_summary,
                    source="existing_segment",
                    display_name=f"{matched_segment.district}{matched_segment.road_name}",
                ),
                matched_segment=matched_segment,
                road_match_status="matched_existing",
            )

        return apply_task_location(
            db,
            task,
            locate_best_srt_location(db, paths),
            road_match_status="unmatched",
            create_segment=False,
        )

    return apply_task_location(
        db,
        task,
        locate_best_srt_location(db, paths),
        road_match_status="not_required",
    )
