from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip().lstrip("\ufeff")
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[7:].lstrip()

    key, separator, value = stripped.partition("=")
    if not separator:
        return None

    key = key.strip()
    if not key:
        return None

    value = value.strip()
    if value and value[0] not in {"'", '"'} and " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return key, _strip_wrapping_quotes(value)


def load_env_files(paths: Iterable[Path]) -> list[Path]:
    loaded_paths: list[Path] = []
    locked_keys = set(os.environ)

    for path in paths:
        if not path.exists() or not path.is_file():
            continue

        for line in path.read_text(encoding="utf-8").splitlines():
            parsed = parse_env_line(line)
            if not parsed:
                continue

            key, value = parsed
            if key in locked_keys:
                continue
            os.environ[key] = value

        loaded_paths.append(path)

    return loaded_paths


def get_default_env_paths() -> list[Path]:
    backend_dir = Path(__file__).resolve().parents[1]
    project_root = Path(__file__).resolve().parents[2]
    return [
        project_root / ".env",
        project_root / ".env.local",
        backend_dir / ".env",
        backend_dir / ".env.local",
    ]


def load_project_env() -> list[Path]:
    return load_env_files(get_default_env_paths())
