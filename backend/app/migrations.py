from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


def _column_names(engine: Engine, table_name: str) -> set[str]:
    with engine.connect() as connection:
        rows = connection.execute(text(f"PRAGMA table_info({table_name})")).mappings().all()
    return {str(row["name"]) for row in rows}


def _table_exists(engine: Engine, table_name: str) -> bool:
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name"),
            {"table_name": table_name},
        ).first()
    return row is not None


def _ensure_identity_tables(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS crack_identity (
                    id INTEGER NOT NULL PRIMARY KEY,
                    identity_code VARCHAR(64) NOT NULL UNIQUE,
                    road_segment_id INTEGER,
                    road_name VARCHAR(64) NOT NULL,
                    district VARCHAR(64) NOT NULL,
                    crack_type VARCHAR(32) NOT NULL DEFAULT 'unknown',
                    lifecycle_status VARCHAR(32) NOT NULL DEFAULT 'active',
                    maintenance_status VARCHAR(32) NOT NULL DEFAULT 'unrepaired',
                    priority_level VARCHAR(16) NOT NULL DEFAULT '低',
                    observation_count INTEGER NOT NULL DEFAULT 0,
                    first_seen_at DATETIME,
                    last_seen_at DATETIME,
                    last_task_id INTEGER,
                    center_longitude FLOAT NOT NULL,
                    center_latitude FLOAT NOT NULL,
                    latest_longitude FLOAT NOT NULL,
                    latest_latitude FLOAT NOT NULL,
                    current_severity_level INTEGER NOT NULL DEFAULT 1,
                    current_severity_label VARCHAR(16) NOT NULL DEFAULT '轻微',
                    current_severity_score FLOAT NOT NULL DEFAULT 0.0,
                    current_length_m FLOAT NOT NULL DEFAULT 0.0,
                    current_avg_width_cm FLOAT NOT NULL DEFAULT 0.0,
                    current_max_width_cm FLOAT NOT NULL DEFAULT 0.0,
                    current_area_m2 FLOAT NOT NULL DEFAULT 0.0,
                    max_severity_level INTEGER NOT NULL DEFAULT 1,
                    max_area_m2 FLOAT NOT NULL DEFAULT 0.0,
                    growth_area_m2 FLOAT NOT NULL DEFAULT 0.0,
                    growth_length_m FLOAT NOT NULL DEFAULT 0.0,
                    latest_original_image_uri VARCHAR(255),
                    latest_result_image_uri VARCHAR(255),
                    feature_hash VARCHAR(64),
                    feature_json TEXT,
                    embedding_model VARCHAR(64),
                    embedding_json TEXT,
                    embedding_count INTEGER NOT NULL DEFAULT 0,
                    remark VARCHAR(255),
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(road_segment_id) REFERENCES road_segment (id),
                    FOREIGN KEY(last_task_id) REFERENCES inspection_task (id)
                )
                """
            )
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_crack_identity_road_name ON crack_identity (road_name)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_crack_identity_lifecycle_status ON crack_identity (lifecycle_status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_crack_identity_priority_level ON crack_identity (priority_level)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_crack_identity_last_seen_at ON crack_identity (last_seen_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_crack_identity_feature_hash ON crack_identity (feature_hash)"))

        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS maintenance_record (
                    id INTEGER NOT NULL PRIMARY KEY,
                    identity_id INTEGER NOT NULL,
                    task_id INTEGER,
                    action_type VARCHAR(32) NOT NULL DEFAULT 'repair',
                    status VARCHAR(32) NOT NULL DEFAULT 'planned',
                    priority_level VARCHAR(16) NOT NULL DEFAULT '中',
                    description TEXT,
                    repaired_by VARCHAR(64),
                    planned_at DATETIME,
                    completed_at DATETIME,
                    before_record_id INTEGER,
                    after_record_id INTEGER,
                    review_result VARCHAR(32),
                    review_notes TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(identity_id) REFERENCES crack_identity (id),
                    FOREIGN KEY(task_id) REFERENCES inspection_task (id),
                    FOREIGN KEY(before_record_id) REFERENCES crack_record (id),
                    FOREIGN KEY(after_record_id) REFERENCES crack_record (id)
                )
                """
            )
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_maintenance_record_identity_id ON maintenance_record (identity_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_maintenance_record_status ON maintenance_record (status)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_maintenance_record_review_result ON maintenance_record (review_result)"))


def _ensure_frame_table(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS inspection_frame (
                    id INTEGER NOT NULL PRIMARY KEY,
                    task_id INTEGER NOT NULL,
                    road_segment_id INTEGER,
                    frame_code VARCHAR(64) NOT NULL UNIQUE,
                    road_name VARCHAR(64) NOT NULL,
                    district VARCHAR(64) NOT NULL,
                    captured_at DATETIME,
                    elapsed_seconds FLOAT NOT NULL DEFAULT 0.0,
                    longitude FLOAT NOT NULL,
                    latitude FLOAT NOT NULL,
                    original_image_uri VARCHAR(255) NOT NULL,
                    result_image_uri VARCHAR(255) NOT NULL,
                    mask_image_uri VARCHAR(255),
                    crack_count INTEGER NOT NULL DEFAULT 0,
                    max_severity_level INTEGER NOT NULL DEFAULT 0,
                    max_severity_label VARCHAR(16) NOT NULL DEFAULT '未检测到',
                    total_area_m2 FLOAT NOT NULL DEFAULT 0.0,
                    remark VARCHAR(255),
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(task_id) REFERENCES inspection_task (id),
                    FOREIGN KEY(road_segment_id) REFERENCES road_segment (id)
                )
                """
            )
        )
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_inspection_frame_task_id ON inspection_frame (task_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_inspection_frame_road_segment_id ON inspection_frame (road_segment_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_inspection_frame_road_name ON inspection_frame (road_name)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_inspection_frame_captured_at ON inspection_frame (captured_at)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_inspection_frame_max_severity_level ON inspection_frame (max_severity_level)"))


def _backfill_crack_identities(engine: Engine) -> None:
    if not _table_exists(engine, "crack_record") or not _table_exists(engine, "crack_identity"):
        return

    crack_record_columns = _column_names(engine, "crack_record")
    if "identity_id" not in crack_record_columns:
        return

    with engine.begin() as connection:
        rows = connection.execute(
            text(
                """
                SELECT c.id, c.task_id, c.road_segment_id, c.crack_code, c.road_name, c.district, c.crack_type,
                       c.severity_level, c.severity_label, c.severity_score, c.length_m, c.avg_width_cm,
                       c.max_width_cm, c.area_m2, c.longitude, c.latitude, c.original_image_uri,
                       c.result_image_uri, c.detected_at, c.created_at
                FROM crack_record c
                LEFT JOIN inspection_task t ON t.id = c.task_id
                WHERE c.identity_id IS NULL
                  AND NOT (
                    COALESCE(t.task_type, 'inspection') = 'review'
                    AND COALESCE(t.road_match_status, 'unmatched') != 'matched_existing'
                  )
                ORDER BY c.detected_at ASC, c.id ASC
                """
            )
        ).mappings().all()

        for row in rows:
            identity_code = f"CID-{int(row['id']):06d}"
            existing = connection.execute(
                text("SELECT id FROM crack_identity WHERE identity_code=:identity_code"),
                {"identity_code": identity_code},
            ).first()
            if existing:
                identity_id = int(existing[0])
            else:
                severity_level = int(row["severity_level"] or 1)
                priority_level = "高" if severity_level >= 3 else "中" if severity_level == 2 else "低"
                result = connection.execute(
                    text(
                        """
                        INSERT INTO crack_identity (
                            identity_code, road_segment_id, road_name, district, crack_type,
                            lifecycle_status, maintenance_status, priority_level, observation_count,
                            first_seen_at, last_seen_at, last_task_id, center_longitude, center_latitude,
                            latest_longitude, latest_latitude, current_severity_level, current_severity_label,
                            current_severity_score, current_length_m, current_avg_width_cm,
                            current_max_width_cm, current_area_m2, max_severity_level, max_area_m2,
                            growth_area_m2, growth_length_m, latest_original_image_uri, latest_result_image_uri,
                            created_at, updated_at
                        )
                        VALUES (
                            :identity_code, :road_segment_id, :road_name, :district, :crack_type,
                            'active', 'unrepaired', :priority_level, 1,
                            :detected_at, :detected_at, :task_id, :longitude, :latitude,
                            :longitude, :latitude, :severity_level, :severity_label,
                            :severity_score, :length_m, :avg_width_cm,
                            :max_width_cm, :area_m2, :severity_level, :area_m2,
                            0.0, 0.0, :original_image_uri, :result_image_uri, :created_at, :created_at
                        )
                        """
                    ),
                    {
                        **dict(row),
                        "identity_code": identity_code,
                        "priority_level": priority_level,
                    },
                )
                identity_id = int(result.lastrowid)

            connection.execute(
                text("UPDATE crack_record SET identity_id=:identity_id WHERE id=:record_id"),
                {"identity_id": identity_id, "record_id": int(row["id"])},
            )


def _backfill_inspection_frames(engine: Engine) -> None:
    if not _table_exists(engine, "crack_record") or not _table_exists(engine, "inspection_frame"):
        return

    crack_record_columns = _column_names(engine, "crack_record")
    if "frame_id" not in crack_record_columns:
        return

    with engine.begin() as connection:
        rows = connection.execute(
            text(
                """
                SELECT id, task_id, road_segment_id, crack_code, road_name, district, severity_level,
                       severity_label, area_m2, longitude, latitude, original_image_uri, result_image_uri,
                       detected_at, created_at, remark
                FROM crack_record
                WHERE frame_id IS NULL
                ORDER BY detected_at ASC, id ASC
                """
            )
        ).mappings().all()

        for row in rows:
            frame_code = f"FRM-BACKFILL-{int(row['id']):06d}"
            existing = connection.execute(
                text("SELECT id FROM inspection_frame WHERE frame_code=:frame_code"),
                {"frame_code": frame_code},
            ).first()
            if existing:
                frame_id = int(existing[0])
            else:
                result = connection.execute(
                    text(
                        """
                        INSERT INTO inspection_frame (
                            task_id, road_segment_id, frame_code, road_name, district,
                            captured_at, elapsed_seconds, longitude, latitude,
                            original_image_uri, result_image_uri, mask_image_uri,
                            crack_count, max_severity_level, max_severity_label,
                            total_area_m2, remark, created_at
                        )
                        VALUES (
                            :task_id, :road_segment_id, :frame_code, :road_name, :district,
                            :detected_at, 0.0, :longitude, :latitude,
                            :original_image_uri, :result_image_uri, NULL,
                            1, :severity_level, :severity_label,
                            :area_m2, :remark, :created_at
                        )
                        """
                    ),
                    {
                        **dict(row),
                        "frame_code": frame_code,
                    },
                )
                frame_id = int(result.lastrowid)

            connection.execute(
                text("UPDATE crack_record SET frame_id=:frame_id WHERE id=:record_id"),
                {"frame_id": frame_id, "record_id": int(row["id"])},
            )


def migrate_database(engine: Engine) -> None:
    """Keep the SQLite demo database compatible with the current models."""
    inspection_task_columns = _column_names(engine, "inspection_task")
    with engine.begin() as connection:
        if "task_type" not in inspection_task_columns:
            connection.execute(text("ALTER TABLE inspection_task ADD COLUMN task_type VARCHAR(32) NOT NULL DEFAULT 'inspection'"))
        if "road_match_status" not in inspection_task_columns:
            connection.execute(text("ALTER TABLE inspection_task ADD COLUMN road_match_status VARCHAR(32) NOT NULL DEFAULT 'pending'"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_inspection_task_road_match_status ON inspection_task (road_match_status)"))
        if "progress_percent" not in inspection_task_columns:
            connection.execute(text("ALTER TABLE inspection_task ADD COLUMN progress_percent INTEGER NOT NULL DEFAULT 0"))
        if "progress_message" not in inspection_task_columns:
            connection.execute(text("ALTER TABLE inspection_task ADD COLUMN progress_message VARCHAR(255) NOT NULL DEFAULT '待启动'"))

    _ensure_identity_tables(engine)
    _ensure_frame_table(engine)

    crack_record_columns = _column_names(engine, "crack_record")
    with engine.begin() as connection:
        if "identity_id" not in crack_record_columns:
            connection.execute(text("ALTER TABLE crack_record ADD COLUMN identity_id INTEGER"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_crack_record_identity_id ON crack_record (identity_id)"))
        if "frame_id" not in crack_record_columns:
            connection.execute(text("ALTER TABLE crack_record ADD COLUMN frame_id INTEGER"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_crack_record_frame_id ON crack_record (frame_id)"))
        if "embedding_model" not in crack_record_columns:
            connection.execute(text("ALTER TABLE crack_record ADD COLUMN embedding_model VARCHAR(64)"))
        if "embedding_json" not in crack_record_columns:
            connection.execute(text("ALTER TABLE crack_record ADD COLUMN embedding_json TEXT"))

    crack_identity_columns = _column_names(engine, "crack_identity")
    with engine.begin() as connection:
        if "embedding_model" not in crack_identity_columns:
            connection.execute(text("ALTER TABLE crack_identity ADD COLUMN embedding_model VARCHAR(64)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_crack_identity_embedding_model ON crack_identity (embedding_model)"))
        if "embedding_json" not in crack_identity_columns:
            connection.execute(text("ALTER TABLE crack_identity ADD COLUMN embedding_json TEXT"))
        if "embedding_count" not in crack_identity_columns:
            connection.execute(text("ALTER TABLE crack_identity ADD COLUMN embedding_count INTEGER NOT NULL DEFAULT 0"))

    _backfill_crack_identities(engine)
    _backfill_inspection_frames(engine)

    if "confidence" not in _column_names(engine, "crack_record"):
        return

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM crack_record"))
        connection.execute(text("DELETE FROM media_asset"))
        connection.execute(text("DELETE FROM inspection_task"))
        connection.execute(text("ALTER TABLE crack_record DROP COLUMN confidence"))
