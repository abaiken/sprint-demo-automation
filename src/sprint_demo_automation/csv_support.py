from __future__ import annotations

import csv
from pathlib import Path


def read_csv_records(path: str) -> list[dict[str, str]]:
    csv_path = Path(path)
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        return [normalize_row(row) for row in reader]


def normalize_row(row: dict[str, str]) -> dict[str, str]:
    return {normalize_header(key): (value or "").strip() for key, value in row.items()}


def normalize_header(value: str) -> str:
    return str(value or "").strip().lower().replace("_", " ").replace("  ", " ")


def get_named_value(row: dict[str, str], *names: str) -> str:
    for name in names:
        key = normalize_header(name)
        if key in row:
            return row[key]
    return ""
