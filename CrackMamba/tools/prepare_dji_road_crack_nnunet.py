#!/usr/bin/env python3
"""Prepare grouped train/validation/test splits from the DJI annotation manifest."""

from __future__ import annotations

import argparse
import itertools
import json
import random
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


COMPLETED_STATUSES = {"annotated", "negative"}


@dataclass(frozen=True)
class Case:
    case_id: str
    segment: str
    source_video: str
    positive: bool
    image_path: Path
    label_path: Path
    dataset_split: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare DJI road-crack annotations as an nnU-Net dataset."
    )
    parser.add_argument("--annotation-root", type=Path, required=True)
    parser.add_argument(
        "--additional-annotation-root",
        type=Path,
        help=(
            "Optional completed annotation set whose manifest explicitly marks every "
            "candidate as dataset_split=train or dataset_split=test."
        ),
    )
    parser.add_argument("--nnunet-raw", type=Path, required=True)
    parser.add_argument("--dataset-id", type=int, default=230)
    parser.add_argument("--dataset-name", default="DJIRoadCrack")
    parser.add_argument("--test-fraction", type=float, default=0.2)
    parser.add_argument(
        "--validation-fraction",
        type=float,
        default=0.1,
        help="Fraction of the non-test pool reserved for nnU-Net validation.",
    )
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument(
        "--test-group-by",
        choices=("source_video", "segment"),
        default="source_video",
        help="source_video gives the strictest held-out test set.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing prepared dataset directory.",
    )
    return parser.parse_args()


def source_video_from_segment(segment: str) -> str:
    return re.sub(r"_seg\d+$", "", segment, flags=re.IGNORECASE)


def load_cases(annotation_root: Path) -> list[Case]:
    manifest_path = annotation_root / "annotation_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Annotation manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    candidates = manifest.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("annotation_manifest.json has no candidates list")

    cases: list[Case] = []
    incomplete: list[str] = []
    for item in candidates:
        status = item.get("status")
        if status not in COMPLETED_STATUSES:
            incomplete.append(str(item.get("id", "<unknown>")))
            continue
        case_id = str(item["id"])
        segment = str(item["segment"])
        image_path = Path(
            item.get("image_path")
            or annotation_root / "imagesTr" / f"{case_id}_0000.png"
        )
        label_path = Path(
            item.get("label_path") or annotation_root / "labelsTr" / f"{case_id}.png"
        )
        if not image_path.is_file():
            raise FileNotFoundError(f"Annotated image not found: {image_path}")
        if not label_path.is_file():
            raise FileNotFoundError(f"Annotated label not found: {label_path}")
        cases.append(
            Case(
                case_id=case_id,
                segment=segment,
                source_video=source_video_from_segment(segment),
                positive=status == "annotated",
                image_path=image_path,
                label_path=label_path,
                dataset_split=item.get("dataset_split"),
            )
        )

    if incomplete:
        raise ValueError(
            f"{len(incomplete)} candidates are not annotated. First cases: {incomplete[:5]}"
        )
    if len(cases) < 10:
        raise ValueError(f"Too few completed cases: {len(cases)}")
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("Duplicate case IDs found in annotation manifest")
    return sorted(cases, key=lambda case: case.case_id)


def split_explicit_cases(cases: list[Case]) -> tuple[list[Case], list[Case]]:
    invalid = [case.case_id for case in cases if case.dataset_split not in {"train", "test"}]
    if invalid:
        raise ValueError(
            "Additional annotations must explicitly use dataset_split=train/test. "
            f"Invalid cases: {invalid[:5]}"
        )
    train = [case for case in cases if case.dataset_split == "train"]
    test = [case for case in cases if case.dataset_split == "test"]
    if not train or not test:
        raise ValueError("Additional annotations must contain both train and test cases")
    return train, test


def choose_holdout_groups(
    cases: list[Case],
    group_key: Callable[[Case], str],
    fraction: float,
    seed: int,
) -> set[str]:
    groups: dict[str, list[Case]] = {}
    for case in cases:
        groups.setdefault(group_key(case), []).append(case)
    if len(groups) < 2:
        raise ValueError("Grouped splitting requires at least two distinct groups")

    names = sorted(groups)
    random.Random(seed).shuffle(names)
    total = len(cases)
    target_count = total * fraction
    overall_positive_rate = sum(case.positive for case in cases) / total
    target_group_count = len(names) * fraction
    best_score: tuple[float, int] | None = None
    best_names: tuple[str, ...] | None = None

    # Current DJI datasets have few groups. Exhaustive search gives a much more
    # balanced sample count than GroupShuffleSplit when group sizes differ.
    if len(names) > 22:
        raise ValueError("More than 22 groups are not supported by exhaustive grouped splitting")
    tie_index = 0
    for selected_count in range(1, len(names)):
        for selected_names in itertools.combinations(names, selected_count):
            selected_cases = [case for name in selected_names for case in groups[name]]
            selected_size = len(selected_cases)
            selected_positive_rate = (
                sum(case.positive for case in selected_cases) / selected_size
            )
            score = (
                abs(selected_size - target_count) / total
                + 0.25 * abs(selected_positive_rate - overall_positive_rate)
                + 0.02 * abs(selected_count - target_group_count) / len(names)
            )
            candidate_score = (round(score, 12), tie_index)
            if best_score is None or candidate_score < best_score:
                best_score = candidate_score
                best_names = selected_names
            tie_index += 1
    if best_names is None:
        raise RuntimeError("Unable to construct grouped split")
    return set(best_names)


def split_cases(
    cases: list[Case],
    test_fraction: float,
    validation_fraction: float,
    test_group_by: str,
    seed: int,
) -> tuple[list[Case], list[Case], list[Case]]:
    test_key = (
        (lambda case: case.source_video)
        if test_group_by == "source_video"
        else (lambda case: case.segment)
    )
    test_groups = choose_holdout_groups(cases, test_key, test_fraction, seed)
    test = [case for case in cases if test_key(case) in test_groups]
    train_pool = [case for case in cases if test_key(case) not in test_groups]

    validation_groups = choose_holdout_groups(
        train_pool, lambda case: case.segment, validation_fraction, seed + 1
    )
    validation = [case for case in train_pool if case.segment in validation_groups]
    train = [case for case in train_pool if case.segment not in validation_groups]
    if not train or not validation or not test:
        raise RuntimeError("The grouped split produced an empty subset")
    return train, validation, test


def subset_summary(cases: list[Case]) -> dict:
    positive = sum(case.positive for case in cases)
    return {
        "count": len(cases),
        "positive": positive,
        "negative": len(cases) - positive,
        "positive_fraction": round(positive / len(cases), 6),
        "source_videos": sorted({case.source_video for case in cases}),
        "segments": sorted({case.segment for case in cases}),
        "case_ids": [case.case_id for case in cases],
    }


def copy_cases(cases: list[Case], images_dir: Path, labels_dir: Path) -> None:
    for case in cases:
        shutil.copy2(case.image_path, images_dir / f"{case.case_id}_0000.png")
        shutil.copy2(case.label_path, labels_dir / f"{case.case_id}.png")


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare_dataset(args: argparse.Namespace) -> Path:
    if not 0 < args.test_fraction < 1:
        raise ValueError("--test-fraction must be between 0 and 1")
    if not 0 < args.validation_fraction < 1:
        raise ValueError("--validation-fraction must be between 0 and 1")
    if not 1 <= args.dataset_id <= 999:
        raise ValueError("--dataset-id must be between 1 and 999")

    annotation_root = args.annotation_root.resolve()
    nnunet_raw = args.nnunet_raw.resolve()
    dataset_dir = nnunet_raw / f"Dataset{args.dataset_id:03d}_{args.dataset_name}"
    if dataset_dir.exists():
        if not args.overwrite:
            raise FileExistsError(
                f"Prepared dataset already exists: {dataset_dir}. "
                "Use --overwrite only when you intend to rebuild it."
            )
        shutil.rmtree(dataset_dir)

    cases = load_cases(annotation_root)
    train, validation, historical_test = split_cases(
        cases,
        args.test_fraction,
        args.validation_fraction,
        args.test_group_by,
        args.seed,
    )
    additional_root: Path | None = None
    additional_train: list[Case] = []
    if args.additional_annotation_root is not None:
        additional_root = args.additional_annotation_root.resolve()
        additional_cases = load_cases(additional_root)
        duplicate_ids = sorted(
            {case.case_id for case in cases} & {case.case_id for case in additional_cases}
        )
        if duplicate_ids:
            raise ValueError(f"Duplicate case IDs across annotation sets: {duplicate_ids[:5]}")
        additional_train, test = split_explicit_cases(additional_cases)
        train = train + additional_train
    else:
        test = historical_test
    staging = dataset_dir.with_name(f".{dataset_dir.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    images_tr = staging / "imagesTr"
    labels_tr = staging / "labelsTr"
    images_ts = staging / "imagesTs"
    labels_ts = staging / "labelsTs"
    images_ts_historical = staging / "imagesTsHistorical"
    labels_ts_historical = staging / "labelsTsHistorical"
    directories = [images_tr, labels_tr, images_ts, labels_ts]
    if additional_root is not None:
        directories.extend([images_ts_historical, labels_ts_historical])
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

    copy_cases(train + validation, images_tr, labels_tr)
    copy_cases(test, images_ts, labels_ts)
    if additional_root is not None:
        copy_cases(historical_test, images_ts_historical, labels_ts_historical)
    write_json(
        staging / "dataset.json",
        {
            "channel_names": {"0": "R", "1": "G", "2": "B"},
            "labels": {"background": 0, "crack": 1},
            "numTraining": len(train) + len(validation),
            "file_ending": ".png",
            "name": args.dataset_name,
            "overwrite_image_reader_writer": "NaturalImage2DIO",
        },
    )
    splits = [
        {
            "train": [case.case_id for case in train],
            "val": [case.case_id for case in validation],
        }
    ]
    write_json(staging / "splits_final.json", splits)
    write_json(
        staging / "split_report.json",
        {
            "schema_version": 1,
            "seed": args.seed,
            "test_fraction_requested": args.test_fraction,
            "validation_fraction_of_train_pool_requested": args.validation_fraction,
            "test_group_by": args.test_group_by,
            "annotation_root": str(annotation_root),
            "additional_annotation_root": str(additional_root) if additional_root else None,
            "train": subset_summary(train),
            "validation": subset_summary(validation),
            "test": subset_summary(test),
            "base_train": subset_summary([case for case in train if case not in additional_train]),
            "additional_train": subset_summary(additional_train) if additional_train else None,
            "historical_test": subset_summary(historical_test) if additional_root else None,
        },
    )
    dataset_dir.parent.mkdir(parents=True, exist_ok=True)
    staging.rename(dataset_dir)
    return dataset_dir


def main() -> None:
    args = parse_args()
    dataset_dir = prepare_dataset(args)
    report = json.loads((dataset_dir / "split_report.json").read_text(encoding="utf-8"))
    print(f"Prepared: {dataset_dir}")
    for name in ("train", "validation", "test"):
        subset = report[name]
        print(
            f"{name}: count={subset['count']} positive={subset['positive']} "
            f"negative={subset['negative']}"
        )
    print(f"Split report: {dataset_dir / 'split_report.json'}")


if __name__ == "__main__":
    main()
