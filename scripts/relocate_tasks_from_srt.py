from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import models  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.services.geolocation import apply_task_location, locate_srt_file  # noqa: E402


def _parse_task_ids(values: list[str]) -> set[int]:
    task_ids: set[int] = set()
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part:
                task_ids.add(int(part))
    return task_ids


def _srt_media_for_task(task: models.InspectionTask) -> models.MediaAsset | None:
    candidates = [
        media
        for media in task.media_assets
        if media.asset_type == "srt" or media.file_name.lower().endswith(".srt")
    ]
    candidates.sort(key=lambda media: media.created_at)
    return candidates[0] if candidates else None


def relocate_tasks(task_ids: set[int], apply_changes: bool) -> int:
    with SessionLocal() as db:
        query = db.query(models.InspectionTask).order_by(models.InspectionTask.id.asc())
        if task_ids:
            query = query.filter(models.InspectionTask.id.in_(task_ids))

        changed_count = 0
        for task in query.all():
            media = _srt_media_for_task(task)
            if not media:
                print(f"task {task.id}: skip, no SRT media found")
                continue

            srt_path = Path(media.file_path)
            if not srt_path.exists():
                print(f"task {task.id}: skip, missing SRT file: {srt_path}")
                continue

            location = locate_srt_file(db, srt_path)
            old_label = f"{task.road_name} / {task.district}"
            new_label = f"{location.road_name} / {location.district}"
            if old_label == new_label and task.road_segment_id:
                print(f"task {task.id}: unchanged: {new_label}")
                continue

            changed_count += 1
            print(f"task {task.id}: {old_label} -> {new_label} [{location.source}]")
            if not apply_changes:
                continue

            apply_task_location(db, task, location)
            (
                db.query(models.CrackRecord)
                .filter(models.CrackRecord.task_id == task.id)
                .update(
                    {
                        models.CrackRecord.road_name: location.road_name,
                        models.CrackRecord.district: location.district,
                        models.CrackRecord.road_segment_id: task.road_segment_id,
                    },
                    synchronize_session=False,
                )
            )

        if apply_changes:
            db.commit()
        else:
            db.rollback()
    return changed_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-locate existing inspection tasks from uploaded SRT coordinates.")
    parser.add_argument("--task-id", action="append", default=[], help="Task id to relocate. Can be repeated or comma-separated.")
    parser.add_argument("--apply", action="store_true", help="Write changes to the database. Without this flag, only prints a dry run.")
    args = parser.parse_args()

    changed_count = relocate_tasks(_parse_task_ids(args.task_id), args.apply)
    mode = "updated" if args.apply else "would update"
    print(f"{mode} {changed_count} task(s)")


if __name__ == "__main__":
    main()
