#!/usr/bin/env python3
"""Build categorized verb metadata JSON from a category CSV."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT = Path("assets/verbs.json")
REQUIRED_COLUMNS = {
    "word",
    "category_id",
    "category_name_de",
    "category_name_en",
    "category_name_ru",
}


class InputError(RuntimeError):
    """Raised when the input CSV does not have the expected shape."""


def require_value(row: dict[str, str], column: str, path: Path, line_number: int) -> str:
    value = row.get(column, "").strip()
    if not value:
        raise InputError(f"{path}:{line_number}: missing required column {column!r}")
    return value


def load_categories(path: Path) -> dict[str, dict[str, Any]]:
    categories: dict[str, dict[str, Any]] = {}
    category_metadata: dict[str, tuple[str, str, str]] = {}

    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise InputError(f"{path}: expected a CSV header")

        missing_columns = REQUIRED_COLUMNS.difference(reader.fieldnames)
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise InputError(f"{path}: missing required columns: {missing}")

        for line_number, row in enumerate(reader, start=2):
            word = require_value(row, "word", path, line_number)
            category_id = require_value(row, "category_id", path, line_number)
            name_de = require_value(row, "category_name_de", path, line_number)
            name_en = require_value(row, "category_name_en", path, line_number)
            name_ru = require_value(row, "category_name_ru", path, line_number)

            metadata = (name_de, name_en, name_ru)
            existing_metadata = category_metadata.setdefault(category_id, metadata)
            if existing_metadata != metadata:
                raise InputError(
                    f"{path}:{line_number}: inconsistent names for category "
                    f"{category_id!r}"
                )

            category = categories.setdefault(
                category_id,
                {
                    "category_name_de": name_de,
                    "category_name_en": name_en,
                    "category_name_ru": name_ru,
                    "words": [],
                },
            )
            category["words"].append(
                {
                    "base": word,
                    "label": word,
                    "enriched": f"assets/enriched/{word}_enriched.csv",
                }
            )

    return categories


def write_json(path: Path, categories: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(categories, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a German verb category CSV into categorized JSON."
    )
    parser.add_argument(
        "input_csv",
        type=Path,
        help="CSV with word, category_id, and localized category name columns",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"JSON output path to overwrite (default: {DEFAULT_OUTPUT})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    categories = load_categories(args.input_csv)
    write_json(args.output, categories)

    word_count = sum(len(category["words"]) for category in categories.values())
    print(f"Wrote {word_count} verbs in {len(categories)} categories to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
