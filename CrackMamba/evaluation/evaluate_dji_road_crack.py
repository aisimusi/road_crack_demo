#!/usr/bin/env python3
"""Evaluate binary crack masks and write machine-readable metrics."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class Confusion:
    tp: int
    tn: int
    fp: int
    fn: int

    def __add__(self, other: "Confusion") -> "Confusion":
        return Confusion(
            self.tp + other.tp,
            self.tn + other.tn,
            self.fp + other.fp,
            self.fn + other.fn,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate DJI road-crack segmentation masks.")
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    return parser.parse_args()


def safe_div(numerator: float, denominator: float) -> float | None:
    return float(numerator / denominator) if denominator else None


def mean_defined(values: list[float | None]) -> float | None:
    defined = [value for value in values if value is not None]
    return float(np.mean(defined)) if defined else None


def metrics_from_confusion(confusion: Confusion) -> dict[str, float | int | None]:
    tp, tn, fp, fn = confusion.tp, confusion.tn, confusion.fp, confusion.fn
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    specificity = safe_div(tn, tn + fp)
    f1 = safe_div(2 * tp, 2 * tp + fp + fn)
    iou_crack = safe_div(tp, tp + fp + fn)
    iou_background = safe_div(tn, tn + fp + fn)
    return {
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "pixel_accuracy": safe_div(tp + tn, tp + tn + fp + fn),
        "precision": precision,
        "recall_sensitivity": recall,
        "specificity": specificity,
        "balanced_accuracy": mean_defined([recall, specificity]),
        "f1_dice": f1,
        "iou_crack": iou_crack,
        "iou_background": iou_background,
        "mean_iou": mean_defined([iou_crack, iou_background]),
    }


def read_binary_mask(path: Path) -> np.ndarray:
    mask = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise RuntimeError(f"Unable to read mask: {path}")
    return mask > 0


def confusion_for_masks(ground_truth: np.ndarray, prediction: np.ndarray) -> Confusion:
    if ground_truth.shape != prediction.shape:
        raise ValueError(
            f"Mask shape mismatch: ground_truth={ground_truth.shape}, prediction={prediction.shape}"
        )
    return Confusion(
        tp=int(np.count_nonzero(ground_truth & prediction)),
        tn=int(np.count_nonzero(~ground_truth & ~prediction)),
        fp=int(np.count_nonzero(~ground_truth & prediction)),
        fn=int(np.count_nonzero(ground_truth & ~prediction)),
    )


def png_names(directory: Path) -> set[str]:
    if not directory.is_dir():
        raise FileNotFoundError(f"Directory not found: {directory}")
    return {path.name for path in directory.glob("*.png") if path.is_file()}


def evaluate(ground_truth_dir: Path, prediction_dir: Path) -> tuple[dict, list[dict]]:
    ground_truth_names = png_names(ground_truth_dir)
    prediction_names = png_names(prediction_dir)
    missing = sorted(ground_truth_names - prediction_names)
    extra = sorted(prediction_names - ground_truth_names)
    if missing or extra:
        raise FileNotFoundError(
            f"Prediction set mismatch: missing={missing[:5]} ({len(missing)} total), "
            f"extra={extra[:5]} ({len(extra)} total)"
        )

    total = Confusion(0, 0, 0, 0)
    per_case: list[dict] = []
    for name in sorted(ground_truth_names):
        ground_truth = read_binary_mask(ground_truth_dir / name)
        prediction = read_binary_mask(prediction_dir / name)
        confusion = confusion_for_masks(ground_truth, prediction)
        total = total + confusion
        per_case.append({"case": Path(name).stem, **metrics_from_confusion(confusion)})

    metric_names = (
        "pixel_accuracy",
        "precision",
        "recall_sensitivity",
        "specificity",
        "balanced_accuracy",
        "f1_dice",
        "iou_crack",
        "iou_background",
        "mean_iou",
    )
    macro = {
        name: mean_defined([case[name] for case in per_case]) for name in metric_names
    }
    summary = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "case_count": len(per_case),
        "ground_truth_dir": str(ground_truth_dir.resolve()),
        "prediction_dir": str(prediction_dir.resolve()),
        "global_pixel_metrics": metrics_from_confusion(total),
        "macro_case_metrics": macro,
    }
    return summary, per_case


def write_outputs(
    summary: dict, per_case: list[dict], output_json: Path, output_csv: Path
) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    fieldnames = list(per_case[0]) if per_case else ["case"]
    with output_csv.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(per_case)


def format_metric(value: float | None) -> str:
    return "undefined" if value is None else f"{value:.6f}"


def main() -> None:
    args = parse_args()
    summary, per_case = evaluate(args.ground_truth, args.predictions)
    write_outputs(summary, per_case, args.output_json, args.output_csv)
    metrics = summary["global_pixel_metrics"]
    print(f"Evaluated cases: {summary['case_count']}")
    for name in (
        "pixel_accuracy",
        "precision",
        "recall_sensitivity",
        "specificity",
        "f1_dice",
        "iou_crack",
        "mean_iou",
    ):
        print(f"{name}: {format_metric(metrics[name])}")
    print(f"Metrics JSON: {args.output_json.resolve()}")
    print(f"Per-case CSV: {args.output_csv.resolve()}")


if __name__ == "__main__":
    main()
