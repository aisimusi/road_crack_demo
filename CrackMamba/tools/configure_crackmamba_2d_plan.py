#!/usr/bin/env python3
"""Apply CrackMamba-compatible patch and batch sizes to an nnU-Net 2D plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plans_json", type=Path)
    parser.add_argument("--patch-size", type=int, default=448)
    parser.add_argument("--batch-size", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.patch_size < 32 or args.patch_size % 32 != 0:
        raise ValueError("--patch-size must be at least 32 and divisible by 32")
    if args.batch_size < 1:
        raise ValueError("--batch-size must be at least 1")
    if not args.plans_json.is_file():
        raise FileNotFoundError(f"Plans file not found: {args.plans_json}")

    plans = json.loads(args.plans_json.read_text(encoding="utf-8"))
    configuration = plans["configurations"]["2d"]
    old_patch_size = configuration["patch_size"]
    old_batch_size = configuration["batch_size"]
    configuration["patch_size"] = [args.patch_size, args.patch_size]
    configuration["batch_size"] = args.batch_size
    args.plans_json.write_text(json.dumps(plans, indent=4) + "\n", encoding="utf-8")
    print(
        f"Configured {args.plans_json}: patch_size {old_patch_size} -> "
        f"{configuration['patch_size']}, batch_size {old_batch_size} -> {args.batch_size}"
    )


if __name__ == "__main__":
    main()
