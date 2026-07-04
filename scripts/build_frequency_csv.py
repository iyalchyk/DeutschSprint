#!/usr/bin/env python3
"""Join German vocabulary records with DWDS, DeReKo, and GermanAPI data."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT = Path("data/2_interim/german_frequency_join.csv")
DWDS_DETAIL_RE = re.compile(r"\[m1\]\s*(\d+)\s*\|\s*(\d+)\s*\|")
FIELDNAMES = [
    "word",
    "dwds_skalenwert",
    "dwds_freq",
    "dereko_freq",
    "german_api_english",
    "german_api_all_translations",
    "german_api_gender",
    "german_api_pos",
    "german_api_frequency_rank",
    "german_api_example_de",
    "german_api_example_en",
    "german_api_level",
]


class InputError(RuntimeError):
    """Raised when an input file does not have the expected shape."""


def parse_dereko(path: Path) -> dict[str, str]:
    """Return total DeReKo frequency by surface word."""
    frequencies: defaultdict[str, Decimal] = defaultdict(Decimal)

    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.rstrip("\n")
            if not line:
                continue

            columns = line.split("\t")
            if len(columns) != 4:
                raise InputError(
                    f"{path}:{line_number}: expected 4 tab-separated columns"
                )

            word = columns[0].strip()
            try:
                frequency = Decimal(columns[3])
            except InvalidOperation as exc:
                raise InputError(
                    f"{path}:{line_number}: invalid DeReKo frequency {columns[3]!r}"
                ) from exc

            frequencies[word] += frequency

    return {word: decimal_to_integer_string(freq) for word, freq in frequencies.items()}


def parse_dwds(path: Path) -> dict[str, tuple[str, str]]:
    """Return first DWDS scale and frequency-rank pair by word."""
    frequencies: dict[str, tuple[str, str]] = {}
    pending_word: str | None = None

    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            match = DWDS_DETAIL_RE.search(line)
            if match:
                if pending_word is None:
                    raise InputError(
                        f"{path}:{line_number}: DWDS detail line had no preceding word"
                    )
                frequencies.setdefault(pending_word, (match.group(1), match.group(2)))
                pending_word = None
                continue

            pending_word = line

    if pending_word is not None:
        raise InputError(f"{path}: final DWDS word {pending_word!r} had no detail line")

    return frequencies


def load_german_api_records(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, dict):
        raise InputError(f"{path}: expected a JSON object")

    records = payload.get("data")
    if not isinstance(records, list):
        raise InputError(f"{path}: expected a top-level 'data' list")

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise InputError(f"{path}: data[{index}] was not a JSON object")
        if not isinstance(record.get("german"), str) or not record["german"]:
            raise InputError(f"{path}: data[{index}] had no string 'german' field")

    return records


def decimal_to_integer_string(value: Decimal) -> str:
    return str(int(value))


def value_to_string(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).splitlines())


def empty_german_api_record(word: str) -> dict[str, Any]:
    return {"german": word}


def build_rows(
    german_api_records: list[dict[str, Any]],
    dwds_by_word: dict[str, tuple[str, str]],
    dereko_by_word: dict[str, str],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    records_by_word: list[dict[str, Any]] = list(german_api_records)
    german_api_words = {record["german"] for record in german_api_records}
    extra_words = [
        word
        for word in dict.fromkeys([*dwds_by_word.keys(), *dereko_by_word.keys()])
        if word not in german_api_words
    ]
    records_by_word.extend(empty_german_api_record(word) for word in extra_words)

    for record in records_by_word:
        word = record["german"]
        dwds_skalenwert, dwds_freq = dwds_by_word.get(word, ("", ""))

        rows.append(
            {
                "word": word,
                "dwds_skalenwert": dwds_skalenwert,
                "dwds_freq": dwds_freq,
                "dereko_freq": dereko_by_word.get(word, ""),
                "german_api_english": value_to_string(record.get("english")),
                "german_api_all_translations": value_to_string(
                    record.get("all_translations")
                ),
                "german_api_gender": value_to_string(record.get("gender")),
                "german_api_pos": value_to_string(record.get("pos")),
                "german_api_frequency_rank": value_to_string(
                    record.get("frequency_rank")
                ),
                "german_api_example_de": value_to_string(record.get("example_de")),
                "german_api_example_en": value_to_string(record.get("example_en")),
                "german_api_level": value_to_string(record.get("level")),
            }
        )

    return rows


def write_pipe_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=FIELDNAMES,
            delimiter="|",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a pipe-separated CSV joining German words from GermanAPI, "
            "DWDS, and DeReKo sources."
        )
    )
    parser.add_argument("dereko_file", type=Path, help="DeReKo .freq input file")
    parser.add_argument("dwds_file", type=Path, help="DWDS frequency text input file")
    parser.add_argument(
        "german_api_json",
        type=Path,
        help="GermanAPI combined JSON dump with a top-level data list",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output pipe-separated CSV path (default: {DEFAULT_OUTPUT})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    dereko_by_word = parse_dereko(args.dereko_file)
    dwds_by_word = parse_dwds(args.dwds_file)
    german_api_records = load_german_api_records(args.german_api_json)
    rows = build_rows(german_api_records, dwds_by_word, dereko_by_word)
    write_pipe_csv(args.output, rows)

    print(f"Wrote {len(rows)} rows to {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InputError as exc:
        raise SystemExit(str(exc))
