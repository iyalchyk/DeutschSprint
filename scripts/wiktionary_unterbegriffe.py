#!/usr/bin/env python3
"""Export German Wiktionary Unterbegriffe with CEFR levels and frequencies."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from pathlib import Path


WIKTIONARY_API_URL = "https://de.wiktionary.org/w/api.php"
DEFAULT_WORD_METADATA_SOURCE = "data/2_interim/german_frequency_join.csv"
DEFAULT_OUTPUT_DIR = Path("data/3_output")

CEFR_LEVELS = {"A1", "A2", "B1", "B2", "C1", "C2"}
TERM_SECTION_TEMPLATES = ("Unterbegriffe", "Wortbildungen")
CSV_COLUMNS = ["word_base", "word", "word_level", "word_freq"]
USER_AGENT = "DeutschSprint/0.1 (+https://github.com/) Python urllib"


class ResourceError(RuntimeError):
    """Raised when an external resource cannot be read or parsed."""


def fetch_url(url: str, timeout: float) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except urllib.error.URLError as exc:
        raise ResourceError(f"failed to fetch {url}: {exc}") from exc


def read_source(source: str, timeout: float) -> str:
    if source.startswith(("http://", "https://")):
        return fetch_url(source, timeout)
    try:
        return Path(source).read_text(encoding="utf-8")
    except OSError as exc:
        raise ResourceError(f"failed to read {source}: {exc}") from exc


def fetch_wiktionary_wikitext(word: str, timeout: float) -> str:
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "prop": "revisions",
        "rvprop": "content",
        "rvslots": "main",
        "titles": word,
    }
    url = f"{WIKTIONARY_API_URL}?{urllib.parse.urlencode(params)}"
    data = json.loads(fetch_url(url, timeout))
    page = data.get("query", {}).get("pages", [{}])[0]
    if page.get("missing"):
        raise ResourceError(f"Wiktionary page not found for {word!r}")

    revisions = page.get("revisions") or []
    if not revisions:
        raise ResourceError(f"Wiktionary page for {word!r} has no revisions")

    slots = revisions[0].get("slots") or {}
    main_slot = slots.get("main") or {}
    content = main_slot.get("content")
    if not isinstance(content, str):
        raise ResourceError(f"Wiktionary response for {word!r} had no page text")
    return content


def extract_german_section(wikitext: str) -> str:
    lines = wikitext.splitlines()
    start = None
    for index, line in enumerate(lines):
        if re.match(r"^==\s*.+\(\{\{Sprache\|Deutsch\}\}\)\s*==\s*$", line):
            start = index + 1
            break

    if start is None:
        return wikitext

    end = len(lines)
    for index in range(start, len(lines)):
        if re.match(r"^==[^=].*==\s*$", lines[index]):
            end = index
            break
    return "\n".join(lines[start:end])


def extract_unterbegriffe(wikitext: str) -> list[str]:
    section = extract_german_section(wikitext)
    lines = section.splitlines()

    for template_name in TERM_SECTION_TEMPLATES:
        terms = extract_linked_template_section(lines, template_name)
        if terms:
            return terms

    return []


def extract_linked_template_section(lines: list[str], template_name: str) -> list[str]:
    in_term_section = False
    terms: list[str] = []
    seen: set[str] = set()

    for line in lines:
        stripped = line.strip()
        if re.fullmatch(r"\{\{\s*" + re.escape(template_name) + r"\s*\}\}", stripped):
            in_term_section = True
            continue

        if not in_term_section:
            continue

        if re.match(r"^=+", stripped) and terms:
            break
        if re.fullmatch(r"\{\{[^{}]+\}\}", stripped) and terms:
            break
        if stripped.startswith("{{") and template_name not in stripped and terms:
            break
        if not stripped and terms:
            break

        for term in linked_terms(stripped):
            key = term.casefold()
            if key not in seen:
                seen.add(key)
                terms.append(term)

    return terms


def linked_terms(line: str) -> Iterable[str]:
    for match in re.finditer(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]", line):
        target, label = match.groups()
        term = clean_wiki_label(label or target)
        if not term or ":" in term:
            continue
        yield term


def clean_wiki_label(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"'{2,}", "", value)
    value = value.replace("_", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def load_level_map(source: str, timeout: float) -> dict[str, str]:
    text = read_source(source, timeout)
    levels = parse_joined_level_table(text)
    if levels:
        return levels

    levels: dict[str, str] = {}
    for row in parse_table_rows(text):
        word, level = find_word_and_level(row)
        if word and level:
            levels[normal_key(word)] = level
    if not levels:
        raise ResourceError(f"no CEFR levels found in {source}")
    return levels


def parse_joined_level_table(text: str) -> dict[str, str]:
    levels: dict[str, str] = {}
    for row in parse_dict_rows(text):
        word = row.get("word", "").strip()
        level = row.get("german_api_level", "").strip().upper()
        if word and level in CEFR_LEVELS:
            levels[normal_key(word)] = level
    return levels


def parse_table_rows(text: str) -> Iterable[list[str]]:
    delimiter = detect_delimiter(text)
    reader = csv.reader(text.splitlines(), delimiter=delimiter)
    for row in reader:
        cleaned = [cell.strip() for cell in row]
        if any(cleaned):
            yield cleaned


def parse_dict_rows(text: str) -> Iterable[dict[str, str]]:
    delimiter = detect_delimiter(text)
    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
    if reader.fieldnames is None:
        return

    for row in reader:
        if row and any((value or "").strip() for value in row.values()):
            yield {key.strip(): (value or "").strip() for key, value in row.items() if key}


def detect_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:10])
    for candidate in ("\t", "|", ",", ";"):
        if candidate in sample:
            return candidate
    return "\t"


def find_word_and_level(row: list[str]) -> tuple[str | None, str | None]:
    lowered = [cell.casefold() for cell in row]
    if "word" in lowered and "level" in lowered:
        return None, None

    level_index = None
    for index, cell in enumerate(row):
        value = cell.strip().upper()
        if value in CEFR_LEVELS:
            level_index = index
            break

    if level_index is None:
        return None, None

    word = next((cell for index, cell in enumerate(row) if index != level_index and cell), None)
    return word, row[level_index].strip().upper()


def load_frequency_map(source: str, timeout: float) -> tuple[dict[str, int], dict[str, int]]:
    text = read_source(source, timeout)
    frequencies = parse_joined_frequency_table(text)
    if not frequencies:
        frequencies = parse_frequency_pairs(text)
    if not frequencies:
        frequencies = parse_frequency_table(text)
    if not frequencies:
        raise ResourceError(f"no word frequencies found in {source}")

    ranks = {word: index for index, word in enumerate(frequencies.keys(), start=1)}
    return frequencies, ranks


def parse_joined_frequency_table(text: str) -> dict[str, int]:
    frequencies: dict[str, int] = {}
    for row in parse_dict_rows(text):
        word = row.get("word", "").strip()
        frequency = row.get("dwds_freq", "").strip()
        if word and frequency.isdigit():
            frequencies[normal_key(word)] = int(frequency)
    return frequencies


def parse_frequency_pairs(text: str) -> dict[str, int]:
    tokens = text.split()
    frequencies: dict[str, int] = {}
    index = 0
    while index + 1 < len(tokens):
        word = tokens[index]
        count = tokens[index + 1]
        if not count.isdigit():
            return {}
        frequencies[normal_key(word)] = int(count)
        index += 2
    return frequencies


def parse_frequency_table(text: str) -> dict[str, int]:
    frequencies: dict[str, int] = {}
    for row in parse_table_rows(text):
        word = None
        count = None
        for cell in row:
            if cell.isdigit():
                count = int(cell)
            elif cell:
                word = cell
        if word and count is not None:
            frequencies[normal_key(word)] = count
    return frequencies


def normal_key(word: str) -> str:
    return re.sub(r"\s+", " ", word.strip()).casefold()


def lookup_word(mapping: dict[str, str] | dict[str, int], word: str):
    for key in lookup_keys(word):
        if key in mapping:
            return mapping[key]
    return None


def lookup_keys(word: str) -> Iterable[str]:
    key = normal_key(word)
    yield key
    if " " in key:
        yield key.replace(" ", "")
    if "-" in key:
        yield key.replace("-", "")


def estimate_level_from_rank(rank: int | None) -> str:
    if rank is None:
        return ""
    if rank <= 1000:
        return "A1"
    if rank <= 2500:
        return "A2"
    if rank <= 5000:
        return "B1"
    if rank <= 10000:
        return "B2"
    if rank <= 20000:
        return "C1"
    return "C2"


def output_words(word_base: str, unterbegriffe: Iterable[str]) -> Iterable[str]:
    seen: set[str] = set()
    for word in itertools.chain((word_base,), unterbegriffe):
        key = normal_key(word)
        if key and key not in seen:
            seen.add(key)
            yield word


def build_rows(
    word_base: str,
    unterbegriffe: Iterable[str],
    levels: dict[str, str],
    frequencies: dict[str, int],
    ranks: dict[str, int],
    infer_missing_level: bool,
) -> Iterable[dict[str, str]]:
    for word in output_words(word_base, unterbegriffe):
        level = lookup_word(levels, word)
        freq = lookup_word(frequencies, word)
        if level is None and infer_missing_level:
            rank = lookup_word(ranks, word)
            level = estimate_level_from_rank(rank)

        yield {
            "word_base": word_base,
            "word": word,
            "word_level": level or "",
            "word_freq": str(freq) if freq is not None else "",
        }


def default_output_path(word: str) -> Path:
    return DEFAULT_OUTPUT_DIR / f"{word}.csv"


def write_rows(rows: Iterable[dict[str, str]], output_path: str | Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_file = output_path.open("w", encoding="utf-8", newline="")

    try:
        writer = csv.DictWriter(
            output_file,
            fieldnames=CSV_COLUMNS,
            delimiter="|",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    finally:
        output_file.close()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch Unterbegriffe or Wortbildungen for a German Wiktionary page and export "
            "CEFR levels plus word frequencies as pipe-separated CSV."
        )
    )
    parser.add_argument("word", help='German base word, for example "lassen".')
    parser.add_argument(
        "-o",
        "--output",
        help="Output CSV path. Defaults to data/3_output/<word>.csv.",
    )
    parser.add_argument(
        "--level-source",
        default=DEFAULT_WORD_METADATA_SOURCE,
        help=(
            "CEFR TSV/CSV source URL or local path. Defaults to "
            "data/2_interim/german_frequency_join.csv using german_api_level."
        ),
    )
    parser.add_argument(
        "--frequency-source",
        default=DEFAULT_WORD_METADATA_SOURCE,
        help=(
            "FrequencyWords-style source URL or local path. Defaults to "
            "data/2_interim/german_frequency_join.csv using dwds_freq."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--no-infer-level",
        action="store_true",
        help="Leave word_level blank when the CEFR source has no exact match.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit the number of exported term rows, useful for smoke tests.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        wikitext = fetch_wiktionary_wikitext(args.word, args.timeout)
        unterbegriffe = extract_unterbegriffe(wikitext)
        if args.limit > 0:
            unterbegriffe = unterbegriffe[: args.limit]
        if not unterbegriffe:
            raise ResourceError(
                f"no Unterbegriffe or Wortbildungen found for {args.word!r}"
            )

        levels = load_level_map(args.level_source, args.timeout)
        frequencies, ranks = load_frequency_map(args.frequency_source, args.timeout)
        rows = build_rows(
            args.word,
            unterbegriffe,
            levels,
            frequencies,
            ranks,
            infer_missing_level=not args.no_infer_level,
        )
        write_rows(rows, args.output or default_output_path(args.word))
    except (ResourceError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
