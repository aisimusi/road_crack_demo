#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import shutil
from datetime import datetime
from pathlib import Path

import numpy as np
from skimage import io

from evaluation.metrics import Evaluator


METADATA_NAMES = {"dataset.json", "plans.json", "predict_from_raw_data_args.json"}


def _png_names(path: Path) -> set[str]:
    return {p.name for p in path.iterdir() if p.is_file() and p.suffix.lower() == ".png"}


def compute_metrics(gt_path: Path, pred_path: Path) -> tuple[dict[str, float], int]:
    gt_names = _png_names(gt_path)
    pred_names = _png_names(pred_path)
    missing = sorted(gt_names - pred_names)
    extra = sorted(pred_names - gt_names)
    if missing or extra:
        raise FileNotFoundError(
            "Prediction files do not match ground truth files. "
            f"missing_pred={len(missing)} first_missing={missing[:5]} "
            f"extra_pred={len(extra)} first_extra={extra[:5]}"
        )

    evaluator = Evaluator(2)
    for name in sorted(gt_names):
        gt = io.imread(gt_path / name, as_gray=True)
        pred = io.imread(pred_path / name)
        gt[gt > 0] = 1
        gt[gt <= 0] = 0
        pred[pred >= 0.5] = 1
        pred[pred < 0.5] = 0
        evaluator.add_batch(gt, pred)

    return {
        "miou": float(evaluator.Mean_Intersection_over_Union()),
        "f1": float(evaluator.F1_Score()),
    }, len(gt_names)


def _load_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _score(value: float) -> float:
    return value if math.isfinite(value) else -math.inf


def is_better(current: dict[str, float], previous: dict | None, primary_metric: str) -> bool:
    if previous is None:
        return True

    previous_metrics = previous.get("metrics", {})
    current_primary = _score(current[primary_metric])
    previous_primary = _score(float(previous_metrics.get(primary_metric, -math.inf)))
    if current_primary > previous_primary:
        return True
    if current_primary < previous_primary:
        return False

    tie_breaker = "miou" if primary_metric != "miou" else "f1"
    return _score(current[tie_breaker]) > _score(float(previous_metrics.get(tie_breaker, -math.inf)))


def copy_model_metadata(model_folder: Path, best_model_folder: Path) -> None:
    best_model_folder.mkdir(parents=True, exist_ok=True)
    for name in ("plans.json", "dataset.json", "dataset_fingerprint.json"):
        src = model_folder / name
        if src.is_file():
            shutil.copy2(src, best_model_folder / name)


def update_best_checkpoint(checkpoint: Path, model_folder: Path, best_model_folder: Path) -> Path:
    if not checkpoint.is_file():
        raise FileNotFoundError(f"Checkpoint not found: {checkpoint}")
    copy_model_metadata(model_folder, best_model_folder)
    best_fold = best_model_folder / "fold_all"
    best_fold.mkdir(parents=True, exist_ok=True)
    best_checkpoint = best_fold / "checkpoint_best.pth"
    shutil.copy2(checkpoint, best_checkpoint)
    return best_checkpoint


def keep_only_global_best(checkpoint_dir: Path, best_checkpoint: Path) -> None:
    if not best_checkpoint.is_file():
        raise FileNotFoundError(f"Global best checkpoint not found: {best_checkpoint}")
    for path in checkpoint_dir.glob("*.pth"):
        path.unlink()
    shutil.copy2(best_checkpoint, checkpoint_dir / "checkpoint_best.pth")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare test metrics and keep only the best checkpoint.")
    parser.add_argument("--gt-path", type=Path, required=True)
    parser.add_argument("--pred-path", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--model-folder", type=Path, required=True)
    parser.add_argument("--best-model-folder", type=Path, required=True)
    parser.add_argument("--dataset-name", required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--primary-metric", choices=("f1", "miou"), default="f1")
    parser.add_argument("--keep-only-global-best-in-checkpoint-dir", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metrics, num_files = compute_metrics(args.gt_path, args.pred_path)
    metrics_path = args.best_model_folder / "best_metrics.json"
    previous = _load_json(metrics_path)
    improved = is_better(metrics, previous, args.primary_metric)

    print(f"Current metrics: mIoU={metrics['miou']:.6f}, F1={metrics['f1']:.6f}, files={num_files}")
    if previous is not None:
        prev = previous["metrics"]
        print(f"Previous best:  mIoU={prev['miou']:.6f}, F1={prev['f1']:.6f}, run={previous.get('run_name')}")

    if improved:
        best_checkpoint = update_best_checkpoint(args.checkpoint, args.model_folder, args.best_model_folder)
        record = {
            "dataset_name": args.dataset_name,
            "run_name": args.run_name,
            "primary_metric": args.primary_metric,
            "metrics": metrics,
            "num_files": num_files,
            "checkpoint_source": str(args.checkpoint),
            "best_checkpoint": str(best_checkpoint),
            "prediction_path": str(args.pred_path),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        args.best_model_folder.mkdir(parents=True, exist_ok=True)
        metrics_path.write_text(json.dumps(record, indent=4), encoding="utf-8")
        print(f"New best checkpoint saved: {best_checkpoint}")
    else:
        best_checkpoint = args.best_model_folder / "fold_all" / "checkpoint_best.pth"
        print(f"No improvement. Keeping existing best checkpoint: {best_checkpoint}")

    if args.keep_only_global_best_in_checkpoint_dir:
        keep_only_global_best(args.checkpoint.parent, best_checkpoint)
        print(f"Cleaned run checkpoints; kept only: {args.checkpoint.parent / 'checkpoint_best.pth'}")


if __name__ == "__main__":
    main()
