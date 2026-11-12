#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Set batch_size for the 2d nnU-Net plan.")
    parser.add_argument("plans_json", type=Path)
    parser.add_argument("batch_size", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.batch_size < 1:
        raise ValueError("batch_size must be >= 1")

    plans = json.loads(args.plans_json.read_text(encoding="utf-8"))
    old_batch_size = plans["configurations"]["2d"]["batch_size"]
    plans["configurations"]["2d"]["batch_size"] = args.batch_size
    args.plans_json.write_text(json.dumps(plans, indent=4), encoding="utf-8")
    print(f"{args.plans_json}: 2d batch_size {old_batch_size} -> {args.batch_size}")


if __name__ == "__main__":
    main()
