#!/usr/bin/env python3
"""Dump German vocabulary API pages for CEFR levels A1 through C1."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_API_URL = "https://german-language.onrender.com/vocab"
DEFAULT_OUTPUT_DIR = Path("data/1_input/GermanAPI")
DEFAULT_COMBINED_NAME = "german_api_all_levels.json"
DEFAULT_LEVELS = ("A1", "A2", "B1", "B2", "C1")
DEFAULT_LIMIT = 500
DEFAULT_TIMEOUT = 30.0
DEFAULT_API_KEY = "demo-key-12345"
USER_AGENT = "DeutschSprint/0.1 (+https://github.com/) Python urllib"


class ApiError(RuntimeError):
    """Raised when the API request or response is invalid."""


def fetch_page(
    api_url: str,
    api_key: str,
    level: str,
    limit: int,
    offset: int,
    timeout: float,
) -> dict[str, Any]:
    params = urllib.parse.urlencode(
        {"level": level, "limit": limit, "offset": offset}
    )
    request = urllib.request.Request(
        f"{api_url}?{params}",
        headers={"User-Agent": USER_AGENT, "X-API-Key": api_key},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise ApiError(
            f"request failed for level={level} offset={offset}: "
            f"HTTP {exc.code} {exc.reason}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise ApiError(
            f"request failed for level={level} offset={offset}: {exc}"
        ) from exc

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ApiError(
            f"response was not valid JSON for level={level} offset={offset}: {exc}"
        ) from exc

    validate_payload(payload, level=level, offset=offset)
    return payload


def validate_payload(payload: dict[str, Any], level: str, offset: int) -> None:
    if not isinstance(payload, dict):
        raise ApiError(
            f"response was not a JSON object for level={level} offset={offset}"
        )

    for key in ("total", "returned", "offset"):
        if not isinstance(payload.get(key), int):
            raise ApiError(
                f"response field {key!r} was not an integer for "
                f"level={level} offset={offset}"
            )

    if not isinstance(payload.get("level"), str):
        raise ApiError(
            f"response field 'level' was not a string for level={level} offset={offset}"
        )

    data = payload.get("data")
    if not isinstance(data, list):
        raise ApiError(
            f"response field 'data' was not a list for level={level} offset={offset}"
        )


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def page_filename(level: str, page_number: int) -> str:
    return f"german_api_{level.lower()}_p{page_number:02d}.json"


def dump_level(
    api_url: str,
    api_key: str,
    level: str,
    output_dir: Path,
    limit: int,
    timeout: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    offset = 0
    page_number = 1
    combined_entries: list[dict[str, Any]] = []
    page_summaries: list[dict[str, Any]] = []
    output_files: list[str] = []
    level_total: int | None = None

    while True:
        payload = fetch_page(
            api_url=api_url,
            api_key=api_key,
            level=level,
            limit=limit,
            offset=offset,
            timeout=timeout,
        )

        filename = page_filename(level, page_number)
        write_json(output_dir / filename, payload)
        output_files.append(filename)

        returned = payload["returned"]
        total = payload["total"]
        api_level = payload["level"]
        data = payload["data"]

        if level_total is None:
            level_total = total
        elif total != level_total:
            raise ApiError(
                f"total changed within level {level}: {level_total} -> {total}"
            )

        for item in data:
            if not isinstance(item, dict):
                raise ApiError(
                    f"data entry was not an object for level={level} offset={offset}"
                )
            merged_item = dict(item)
            merged_item["level"] = level
            if api_level != level:
                merged_item["api_level"] = api_level
            combined_entries.append(merged_item)

        page_summaries.append(
            {
                "level": level,
                "api_level": api_level,
                "page": page_number,
                "offset": payload["offset"],
                "returned": returned,
                "total": total,
                "file": filename,
            }
        )

        if returned <= 0:
            break
        if returned < limit:
            break
        if payload["offset"] + returned >= total:
            break

        offset = payload["offset"] + limit
        page_number += 1

    level_summary = {
        "level": level,
        "total": level_total or 0,
        "pages": len(output_files),
        "records": len(combined_entries),
        "files": output_files,
    }
    return combined_entries, page_summaries, level_summary


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Dump German vocabulary API pages for A1-C1 and write one combined JSON file."
        )
    )
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"API endpoint to query (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("GERMAN_LANGUAGE_API_KEY", DEFAULT_API_KEY),
        help=(
            "API key to send in X-API-Key. "
            "Defaults to $GERMAN_LANGUAGE_API_KEY or demo-key-12345."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for per-page JSON files (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--combined-name",
        default=DEFAULT_COMBINED_NAME,
        help=(
            "Filename for the combined JSON output inside --output-dir "
            f"(default: {DEFAULT_COMBINED_NAME})"
        ),
    )
    parser.add_argument(
        "--levels",
        nargs="+",
        default=list(DEFAULT_LEVELS),
        help=f"CEFR levels to fetch in order (default: {' '.join(DEFAULT_LEVELS)})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Page size to request (default: {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"HTTP timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    if args.limit <= 0:
        raise SystemExit("--limit must be greater than zero")
    if args.timeout <= 0:
        raise SystemExit("--timeout must be greater than zero")

    all_entries: list[dict[str, Any]] = []
    all_pages: list[dict[str, Any]] = []
    level_summaries: list[dict[str, Any]] = []

    for level in args.levels:
        entries, pages, summary = dump_level(
            api_url=args.api_url,
            api_key=args.api_key,
            level=level.upper(),
            output_dir=args.output_dir,
            limit=args.limit,
            timeout=args.timeout,
        )
        all_entries.extend(entries)
        all_pages.extend(pages)
        level_summaries.append(summary)

    combined_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "api_url": args.api_url,
            "levels": [level.upper() for level in args.levels],
            "limit": args.limit,
        },
        "summary": {
            "levels": len(level_summaries),
            "pages": len(all_pages),
            "records": len(all_entries),
        },
        "levels": level_summaries,
        "pages": all_pages,
        "data": all_entries,
    }
    write_json(args.output_dir / args.combined_name, combined_payload)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApiError as exc:
        raise SystemExit(str(exc))
