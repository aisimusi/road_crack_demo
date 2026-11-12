from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.utcnow()


class RoadSegment(Base):
    __tablename__ = "road_segment"
    __table_args__ = (UniqueConstraint("road_name", "district", name="uq_road_segment_name_district"),)

    id = Column(Integer, primary_key=True, index=True)
    road_name = Column(String(64), nullable=False, index=True)
    district = Column(String(64), nullable=False, index=True)
    start_longitude = Column(Float, nullable=True)
    start_latitude = Column(Float, nullable=True)
    end_longitude = Column(Float, nullable=True)
    end_latitude = Column(Float, nullable=True)
    center_longitude = Column(Float, nullable=True)
    center_latitude = Column(Float, nullable=True)
    road_length_km = Column(Float, nullable=True)
    lane_count = Column(Integer, nullable=True)
    remark = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    tasks = relationship("InspectionTask", back_populates="road_segment")
    frames = relationship("InspectionFrame", back_populates="road_segment")
    cracks = relationship("CrackRecord", back_populates="road_segment")
    crack_identities = relationship("CrackIdentity", back_populates="road_segment")


class InspectionTask(Base):
    __tablename__ = "inspection_task"

    id = Column(Integer, primary_key=True, index=True)
    task_name = Column(String(128), nullable=False)
    road_name = Column(String(64), nullable=False, index=True)
    district = Column(String(64), nullable=False, index=True)
    operator_name = Column(String(64), nullable=False)
    task_type = Column(String(32), nullable=False, default="inspection")
    road_match_status = Column(String(32), nullable=False, default="pending", index=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    progress_percent = Column(Integer, nullable=False, default=0)
    progress_message = Column(String(255), nullable=False, default="待启动")
    description = Column(Text, nullable=True)
    scheduled_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    road_segment_id = Column(Integer, ForeignKey("road_segment.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    road_segment = relationship("RoadSegment", back_populates="tasks")
    media_assets = relationship("MediaAsset", back_populates="task", cascade="all, delete-orphan")
    frames = relationship("InspectionFrame", back_populates="task", cascade="all, delete-orphan")
    crack_records = relationship("CrackRecord", back_populates="task", cascade="all, delete-orphan")


class CrackIdentity(Base):
    __tablename__ = "crack_identity"

    id = Column(Integer, primary_key=True, index=True)
    identity_code = Column(String(64), nullable=False, unique=True, index=True)
    road_segment_id = Column(Integer, ForeignKey("road_segment.id"), nullable=True, index=True)
    road_name = Column(String(64), nullable=False, index=True)
    district = Column(String(64), nullable=False, index=True)
    crack_type = Column(String(32), nullable=False, default="unknown")
    lifecycle_status = Column(String(32), nullable=False, default="active", index=True)
    maintenance_status = Column(String(32), nullable=False, default="unrepaired", index=True)
    priority_level = Column(String(16), nullable=False, default="低", index=True)
    observation_count = Column(Integer, nullable=False, default=0)
    first_seen_at = Column(DateTime, nullable=True, index=True)
    last_seen_at = Column(DateTime, nullable=True, index=True)
    last_task_id = Column(Integer, ForeignKey("inspection_task.id"), nullable=True, index=True)
    center_longitude = Column(Float, nullable=False)
    center_latitude = Column(Float, nullable=False)
    latest_longitude = Column(Float, nullable=False)
    latest_latitude = Column(Float, nullable=False)
    current_severity_level = Column(Integer, nullable=False, default=1, index=True)
    current_severity_label = Column(String(16), nullable=False, default="轻微")
    current_severity_score = Column(Float, nullable=False, default=0.0)
    current_length_m = Column(Float, nullable=False, default=0.0)
    current_avg_width_cm = Column(Float, nullable=False, default=0.0)
    current_max_width_cm = Column(Float, nullable=False, default=0.0)
    current_area_m2 = Column(Float, nullable=False, default=0.0)
    max_severity_level = Column(Integer, nullable=False, default=1, index=True)
    max_area_m2 = Column(Float, nullable=False, default=0.0)
    growth_area_m2 = Column(Float, nullable=False, default=0.0)
    growth_length_m = Column(Float, nullable=False, default=0.0)
    latest_original_image_uri = Column(String(255), nullable=True)
    latest_result_image_uri = Column(String(255), nullable=True)
    feature_hash = Column(String(64), nullable=True, index=True)
    feature_json = Column(Text, nullable=True)
    embedding_model = Column(String(64), nullable=True, index=True)
    embedding_json = Column(Text, nullable=True)
    embedding_count = Column(Integer, nullable=False, default=0)
    remark = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    road_segment = relationship("RoadSegment", back_populates="crack_identities")
    records = relationship("CrackRecord", back_populates="identity")
    maintenance_records = relationship("MaintenanceRecord", back_populates="identity", cascade="all, delete-orphan")


class MediaAsset(Base):
    __tablename__ = "media_asset"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("inspection_task.id"), nullable=True, index=True)
    asset_type = Column(String(32), nullable=False, default="image")
    category = Column(String(32), nullable=False, default="original")
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(512), nullable=False)
    file_uri = Column(String(255), nullable=False)
    mime_type = Column(String(64), nullable=False)
    captured_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    task = relationship("InspectionTask", back_populates="media_assets")


class InspectionFrame(Base):
    __tablename__ = "inspection_frame"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("inspection_task.id"), nullable=False, index=True)
    road_segment_id = Column(Integer, ForeignKey("road_segment.id"), nullable=True, index=True)
    frame_code = Column(String(64), nullable=False, unique=True, index=True)
    road_name = Column(String(64), nullable=False, index=True)
    district = Column(String(64), nullable=False, index=True)
    captured_at = Column(DateTime, nullable=True, index=True)
    elapsed_seconds = Column(Float, nullable=False, default=0.0)
    longitude = Column(Float, nullable=False)
    latitude = Column(Float, nullable=False)
    original_image_uri = Column(String(255), nullable=False)
    result_image_uri = Column(String(255), nullable=False)
    mask_image_uri = Column(String(255), nullable=True)
    crack_count = Column(Integer, nullable=False, default=0)
    max_severity_level = Column(Integer, nullable=False, default=0, index=True)
    max_severity_label = Column(String(16), nullable=False, default="未检测到")
    total_area_m2 = Column(Float, nullable=False, default=0.0)
    remark = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    task = relationship("InspectionTask", back_populates="frames")
    road_segment = relationship("RoadSegment", back_populates="frames")
    crack_records = relationship("CrackRecord", back_populates="frame")


class CrackRecord(Base):
    __tablename__ = "crack_record"

    id = Column(Integer, primary_key=True, index=True)
    identity_id = Column(Integer, ForeignKey("crack_identity.id"), nullable=True, index=True)
    frame_id = Column(Integer, ForeignKey("inspection_frame.id"), nullable=True, index=True)
    task_id = Column(Integer, ForeignKey("inspection_task.id"), nullable=False, index=True)
    road_segment_id = Column(Integer, ForeignKey("road_segment.id"), nullable=True, index=True)
    crack_code = Column(String(64), nullable=False, unique=True, index=True)
    road_name = Column(String(64), nullable=False, index=True)
    district = Column(String(64), nullable=False, index=True)
    crack_type = Column(String(32), nullable=False, default="unknown")
    severity_level = Column(Integer, nullable=False, default=1, index=True)
    severity_label = Column(String(16), nullable=False, default="轻微")
    severity_score = Column(Float, nullable=False, default=0.0)
    length_m = Column(Float, nullable=False, default=0.0)
    avg_width_cm = Column(Float, nullable=False, default=0.0)
    max_width_cm = Column(Float, nullable=False, default=0.0)
    area_m2 = Column(Float, nullable=False, default=0.0)
    bbox_x = Column(Integer, nullable=False, default=0)
    bbox_y = Column(Integer, nullable=False, default=0)
    bbox_width = Column(Integer, nullable=False, default=0)
    bbox_height = Column(Integer, nullable=False, default=0)
    longitude = Column(Float, nullable=False)
    latitude = Column(Float, nullable=False)
    original_image_uri = Column(String(255), nullable=False)
    result_image_uri = Column(String(255), nullable=False)
    embedding_model = Column(String(64), nullable=True)
    embedding_json = Column(Text, nullable=True)
    remark = Column(String(255), nullable=True)
    detected_at = Column(DateTime, default=utcnow, nullable=False, index=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    identity = relationship("CrackIdentity", back_populates="records")
    frame = relationship("InspectionFrame", back_populates="crack_records")
    task = relationship("InspectionTask", back_populates="crack_records")
    road_segment = relationship("RoadSegment", back_populates="cracks")


class MaintenanceRecord(Base):
    __tablename__ = "maintenance_record"

    id = Column(Integer, primary_key=True, index=True)
    identity_id = Column(Integer, ForeignKey("crack_identity.id"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("inspection_task.id"), nullable=True, index=True)
    action_type = Column(String(32), nullable=False, default="repair")
    status = Column(String(32), nullable=False, default="planned", index=True)
    priority_level = Column(String(16), nullable=False, default="中", index=True)
    description = Column(Text, nullable=True)
    repaired_by = Column(String(64), nullable=True)
    planned_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    before_record_id = Column(Integer, ForeignKey("crack_record.id"), nullable=True)
    after_record_id = Column(Integer, ForeignKey("crack_record.id"), nullable=True)
    review_result = Column(String(32), nullable=True, index=True)
    review_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    identity = relationship("CrackIdentity", back_populates="maintenance_records")
    task = relationship("InspectionTask")
    before_record = relationship("CrackRecord", foreign_keys=[before_record_id])
    after_record = relationship("CrackRecord", foreign_keys=[after_record_id])


class NLQueryLog(Base):
    __tablename__ = "nl_query_log"

    id = Column(Integer, primary_key=True, index=True)
    question = Column(Text, nullable=False)
    generated_sql = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    success = Column(Boolean, nullable=False, default=False)
    row_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class AgentSession(Base):
    __tablename__ = "agent_session"

    id = Column(Integer, primary_key=True, index=True)
    user_query = Column(Text, nullable=False)
    final_answer = Column(Text, nullable=True)
    debug_intent = Column(String(64), nullable=True)
    status = Column(String(32), nullable=False, default="running", index=True)
    llm_mode = Column(String(16), nullable=False, default="mock")
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)

    todos = relationship("AgentTodo", back_populates="session", cascade="all, delete-orphan")
    tool_calls = relationship("AgentToolCall", back_populates="session", cascade="all, delete-orphan")


class AgentTodo(Base):
    __tablename__ = "agent_todo"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("agent_session.id"), nullable=False, index=True)
    content = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, default="pending")
    step_order = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    session = relationship("AgentSession", back_populates="todos")


class AgentToolCall(Base):
    __tablename__ = "agent_tool_call"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("agent_session.id"), nullable=False, index=True)
    tool_name = Column(String(64), nullable=False, index=True)
    tool_args = Column(Text, nullable=False)
    tool_result = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default="success")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    session = relationship("AgentSession", back_populates="tool_calls")
