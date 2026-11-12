from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMBaseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RoadSegmentBase(BaseModel):
    road_name: str
    district: str
    start_longitude: float | None = None
    start_latitude: float | None = None
    end_longitude: float | None = None
    end_latitude: float | None = None
    center_longitude: float | None = None
    center_latitude: float | None = None
    road_length_km: float | None = None
    lane_count: int | None = None
    remark: str | None = None


class RoadSegmentOut(RoadSegmentBase, ORMBaseModel):
    id: int
    created_at: datetime


class InspectionTaskCreate(BaseModel):
    task_name: str = Field(..., max_length=128)
    road_name: str | None = Field(default=None, max_length=64)
    district: str | None = Field(default=None, max_length=64)
    operator_name: str = Field(..., max_length=64)
    task_type: Literal["inspection", "review"] = "inspection"
    description: str | None = Field(default=None, max_length=1000)
    scheduled_at: datetime | None = None


class InspectionTaskOut(ORMBaseModel):
    id: int
    task_name: str
    road_name: str
    district: str
    operator_name: str
    task_type: str
    road_match_status: str = "pending"
    status: str
    progress_percent: int = 0
    progress_message: str = "待启动"
    description: str | None = None
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    road_segment_id: int | None = None
    created_at: datetime
    updated_at: datetime


class TaskListItem(InspectionTaskOut):
    crack_count: int = 0


class MediaAssetOut(ORMBaseModel):
    id: int
    task_id: int | None = None
    asset_type: str
    category: str
    file_name: str
    file_path: str
    file_uri: str
    mime_type: str
    captured_at: datetime | None = None
    created_at: datetime


class CrackRecordOut(ORMBaseModel):
    id: int
    identity_id: int | None = None
    frame_id: int | None = None
    task_id: int
    road_segment_id: int | None = None
    crack_code: str
    road_name: str
    district: str
    crack_type: str
    severity_level: int
    severity_label: str
    severity_score: float
    length_m: float
    avg_width_cm: float
    max_width_cm: float
    area_m2: float
    bbox_x: int
    bbox_y: int
    bbox_width: int
    bbox_height: int
    longitude: float
    latitude: float
    original_image_uri: str
    result_image_uri: str
    remark: str | None = None
    detected_at: datetime
    created_at: datetime


class CrackIdentityOut(ORMBaseModel):
    id: int
    identity_code: str
    road_segment_id: int | None = None
    road_name: str
    district: str
    crack_type: str
    lifecycle_status: str
    maintenance_status: str
    priority_level: str
    observation_count: int
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    last_task_id: int | None = None
    center_longitude: float
    center_latitude: float
    latest_longitude: float
    latest_latitude: float
    current_severity_level: int
    current_severity_label: str
    current_severity_score: float
    current_length_m: float
    current_avg_width_cm: float
    current_max_width_cm: float
    current_area_m2: float
    max_severity_level: int
    max_area_m2: float
    growth_area_m2: float
    growth_length_m: float
    latest_original_image_uri: str | None = None
    latest_result_image_uri: str | None = None
    remark: str | None = None
    created_at: datetime
    updated_at: datetime


class MaintenanceRecordCreate(BaseModel):
    action_type: str = Field(default="repair", max_length=32)
    status: str = Field(default="planned", max_length=32)
    priority_level: str = Field(default="中", max_length=16)
    description: str | None = Field(default=None, max_length=1000)
    repaired_by: str | None = Field(default=None, max_length=64)
    planned_at: datetime | None = None
    completed_at: datetime | None = None
    before_record_id: int | None = None
    after_record_id: int | None = None
    review_result: str | None = Field(default=None, max_length=32)
    review_notes: str | None = Field(default=None, max_length=1000)


class MaintenanceRecordOut(ORMBaseModel):
    id: int
    identity_id: int
    task_id: int | None = None
    action_type: str
    status: str
    priority_level: str
    description: str | None = None
    repaired_by: str | None = None
    planned_at: datetime | None = None
    completed_at: datetime | None = None
    before_record_id: int | None = None
    after_record_id: int | None = None
    review_result: str | None = None
    review_notes: str | None = None
    created_at: datetime
    updated_at: datetime


class CrackIdentityDetail(CrackIdentityOut):
    records: list[CrackRecordOut] = Field(default_factory=list)
    maintenance_records: list[MaintenanceRecordOut] = Field(default_factory=list)


class CrackObservationImage(BaseModel):
    crack_id: int
    crack_code: str
    task_id: int
    severity_level: int
    severity_label: str
    detected_at: datetime
    original_image_uri: str
    result_image_uri: str
    crop_original_image_uri: str | None = None
    crop_result_image_uri: str | None = None
    bbox_x: int
    bbox_y: int
    bbox_width: int
    bbox_height: int


class FrameCrackOut(BaseModel):
    id: int
    identity_id: int | None = None
    identity_code: str | None = None
    crack_code: str
    crack_type: str
    severity_level: int
    severity_label: str
    length_m: float
    avg_width_cm: float
    max_width_cm: float
    area_m2: float
    longitude: float
    latitude: float
    original_image_uri: str
    result_image_uri: str
    crop_original_image_uri: str | None = None
    crop_result_image_uri: str | None = None
    bbox_x: int
    bbox_y: int
    bbox_width: int
    bbox_height: int


class InspectionFrameOut(ORMBaseModel):
    id: int
    task_id: int
    road_segment_id: int | None = None
    frame_code: str
    road_name: str
    district: str
    task_name: str | None = None
    task_type: str | None = None
    captured_at: datetime | None = None
    elapsed_seconds: float
    longitude: float
    latitude: float
    original_image_uri: str
    result_image_uri: str
    mask_image_uri: str | None = None
    crack_count: int
    max_severity_level: int
    max_severity_label: str
    total_area_m2: float
    remark: str | None = None
    created_at: datetime
    cracks: list[FrameCrackOut] = Field(default_factory=list)


class InspectionFramePage(BaseModel):
    items: list[InspectionFrameOut] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
    total_pages: int


class RoadInspectionSummary(BaseModel):
    road_segment_id: int | None = None
    road_name: str
    district: str
    task_count: int = 0
    frame_count: int = 0
    crack_count: int = 0
    last_detected_at: datetime | None = None


class TaskInspectionDate(BaseModel):
    task_id: int
    task_name: str
    task_type: str
    detected_date: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    frame_count: int = 0
    crack_count: int = 0
    severe_count: int = 0


class CrackIdentityDetailWithImages(CrackIdentityDetail):
    observation_images: list[CrackObservationImage] = Field(default_factory=list)


class TaskDetail(InspectionTaskOut):
    road_segment: RoadSegmentOut | None = None
    media_assets: list[MediaAssetOut] = Field(default_factory=list)
    frames: list[InspectionFrameOut] = Field(default_factory=list)
    crack_records: list[CrackRecordOut] = Field(default_factory=list)


class CrackMapPoint(BaseModel):
    crack_id: int
    identity_id: int | None = None
    frame_id: int | None = None
    identity_code: str | None = None
    crack_code: str
    road_name: str
    district: str
    severity_level: int
    severity_label: str
    crack_type: str
    length_m: float
    avg_width_cm: float
    area_m2: float
    longitude: float
    latitude: float
    result_image_uri: str
    original_image_uri: str | None = None
    mask_image_uri: str | None = None
    detected_at: datetime | None = None
    lifecycle_status: str | None = None
    maintenance_status: str | None = None
    priority_level: str | None = None


class RoadCrackCount(BaseModel):
    road_name: str
    crack_count: int


class CrackStatistics(BaseModel):
    total_cracks: int
    total_observations: int = 0
    total_identities: int = 0
    total_frames: int = 0
    active_identity_count: int = 0
    repaired_identity_count: int = 0
    recurred_identity_count: int = 0
    severe_count: int
    medium_count: int
    minor_count: int
    road_count: int
    task_count: int
    finished_task_count: int
    recent_cracks: list[CrackRecordOut]
    road_breakdown: list[RoadCrackCount]


class RoadCandidate(BaseModel):
    name: str
    distance: float | None = None
    direction: str | None = None
    source: str | None = None
    id: str | None = None


class ReverseGeocodeOut(BaseModel):
    longitude: float
    latitude: float
    coordinate_system: str
    query_longitude: float | None = None
    query_latitude: float | None = None
    road_name: str | None = None
    district: str | None = None
    province: str | None = None
    city: str | None = None
    adcode: str | None = None
    township: str | None = None
    formatted_address: str | None = None
    source: str
    info: str | None = None
    infocode: str | None = None
    road_candidates: list[RoadCandidate] = Field(default_factory=list)


class DetectionStartRequest(BaseModel):
    weight_name: Literal["crack9k", "uav-crack", "earthquake"] = "crack9k"


class DetectionSummary(BaseModel):
    task_id: int
    status: str
    progress_percent: int = 100
    progress_message: str = "检测完成"
    crack_count: int
    severe_count: int
    medium_count: int
    minor_count: int


class DetectionProgress(BaseModel):
    task_id: int
    status: str
    progress_percent: int
    progress_message: str
    crack_count: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None


class NLQueryRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=500)


class NLQueryResponse(BaseModel):
    question: str
    sql: str
    summary: str
    data: list[dict[str, Any]]
    validated_sql_safe: bool


class AgentTodoOut(ORMBaseModel):
    id: int
    session_id: int
    content: str
    status: str
    step_order: int
    created_at: datetime
    updated_at: datetime


class AgentToolCallOut(BaseModel):
    id: int
    session_id: int
    tool_name: str
    tool_args: dict[str, Any]
    tool_result: dict[str, Any] | None = None
    status: str
    error_message: str | None = None
    created_at: datetime


class AgentQueryRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=500)


class AgentDebugInfo(BaseModel):
    llm_mode: str
    steps: int | None = None
    fallback_used: bool | None = None
    fallback_reason: str | None = None
    intent: str | None = None
    generated_at: str | None = None
    status: str | None = None


class AgentQueryResponse(BaseModel):
    session_id: int
    query: str
    answer: str
    todos: list[AgentTodoOut]
    tool_calls: list[AgentToolCallOut]
    stats: dict[str, Any] = Field(default_factory=dict)
    cracks: list[dict[str, Any]] = Field(default_factory=list)
    images: list[dict[str, Any]] = Field(default_factory=list)
    image_analysis: dict[str, Any] = Field(default_factory=dict)
    map_geojson: dict[str, Any] = Field(default_factory=dict)
    maintenance_advice: dict[str, Any] = Field(default_factory=dict)
    debug: AgentDebugInfo


class AgentSessionDetail(BaseModel):
    session_id: int
    query: str
    answer: str
    todos: list[AgentTodoOut]
    tool_calls: list[AgentToolCallOut]
    stats: dict[str, Any] = Field(default_factory=dict)
    cracks: list[dict[str, Any]] = Field(default_factory=list)
    images: list[dict[str, Any]] = Field(default_factory=list)
    image_analysis: dict[str, Any] = Field(default_factory=dict)
    map_geojson: dict[str, Any] = Field(default_factory=dict)
    maintenance_advice: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    finished_at: datetime | None = None
    debug: AgentDebugInfo
