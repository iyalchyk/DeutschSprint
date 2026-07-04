#!/usr/bin/env python3
"""Enrich a word CSV with Gemini and write a pipe-separated CSV."""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

from google import genai
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tqdm import tqdm


DEFAULT_INPUT_DIR = Path("data/3_output")
DEFAULT_OUTPUT_DIR = Path("data/4_enriched_gemini")
DEFAULT_PROMPT_PATH = Path("data/1_input/prompt_01.txt")
DEFAULT_ENV_FILE = Path(".env")
DEFAULT_MODEL = "gemini-3.5-flash"
API_KEY_ENV = "GOOGLE_GEMINI_API_KEY"

INPUT_COLUMNS = ["word_base", "word", "word_level", "word_freq"]
ENRICHED_COLUMNS = [
    "word_translation_en",
    "word_translation_ru",
    "word_synonyms",
    "sentence_example",
    "sentence_example_translation_en",
    "sentence_example_translation_ru",
    "sentence_synonym",
    "typical_collocations",
    "usage_comments_en",
]
OUTPUT_COLUMNS = INPUT_COLUMNS + ENRICHED_COLUMNS


class EnrichedWordRow(BaseModel):
    """One row in the enriched CSV output."""

    model_config = ConfigDict(extra="forbid")

    word_base: str
    word: str
    word_level: str
    word_freq: str
    word_translation_en: str = Field(description="English translation of word.")
    word_translation_ru: str = Field(description="Russian translation of word.")
    word_synonyms: str = Field(
        description="German synonyms separated with semicolons when there are several."
    )
    sentence_example: str = Field(description="Short German example sentence.")
    sentence_example_translation_en: str = Field(
        description="English translation of sentence_example."
    )
    sentence_example_translation_ru: str = Field(
        description="Russian translation of sentence_example."
    )
    sentence_synonym: str = Field(
        description=(
            "German paraphrase of sentence_example using one synonym, or other wording "
            "if there is no exact synonym."
        )
    )
    typical_collocations: str = Field(
        description="Typical German collocations separated with semicolons."
    )
    usage_comments_en: str = Field(
        description=(
            "English usage note covering register, common constructions, governance, "
            "and contrast with similar words."
        )
    )


class EnrichedCsv(BaseModel):
    """Complete enriched CSV payload returned by Gemini."""

    model_config = ConfigDict(extra="forbid")

    rows: list[EnrichedWordRow] = Field(
        description="Rows in the same order as the input CSV."
    )


class EnrichmentError(RuntimeError):
    """Raised when enrichment cannot be completed."""


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Load data/3_output/<word>.csv files, enrich them with Gemini, and write "
            "data/4_enriched_gemini/<word>_enriched.csv."
        )
    )
    parser.add_argument(
        "word",
        nargs="?",
        help="Base word, e.g. weisen. If omitted, enrich all CSV files in --input-dir.",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Directory containing <word>.csv files (default: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for enriched CSV files (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--prompt",
        type=Path,
        default=DEFAULT_PROMPT_PATH,
        help=f"Prompt file to send before the CSV content (default: {DEFAULT_PROMPT_PATH})",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="Optional .env file to load when GOOGLE_GEMINI_API_KEY is not exported.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Gemini model name (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing output file.",
    )
    return parser.parse_args(argv)


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file, delimiter="|")
        rows = list(reader)

    fieldnames = reader.fieldnames or []
    missing_columns = [column for column in INPUT_COLUMNS if column not in fieldnames]
    if missing_columns:
        raise EnrichmentError(
            f"{path} is missing required columns: {', '.join(missing_columns)}"
        )
    if not rows:
        raise EnrichmentError(f"{path} has no data rows")
    return fieldnames, rows


def rows_to_pipe_csv(fieldnames: list[str], rows: list[dict[str, str]]) -> str:
    lines = ["|".join(fieldnames)]
    for row in rows:
        lines.append("|".join(row.get(field, "") for field in fieldnames))
    return "\n".join(lines)


def build_prompt(prompt_text: str, input_filename: str, csv_text: str) -> str:
    return (
        f"{prompt_text.strip()}\n\n"
        f"INPUT_FILENAME: {input_filename}\n\n"
        "Return JSON that conforms to the provided response schema. "
        "Keep the number and order of rows identical to the input CSV. "
        "Preserve word_base, word, word_level, and word_freq exactly. "
        "Do not use newline or pipe characters inside field values.\n\n"
        "Input pipe-separated CSV:\n"
        f"{csv_text}\n"
    )


def enrich_with_gemini(api_key: str, model: str, prompt: str) -> EnrichedCsv:
    client = genai.Client(api_key=api_key)
    response = client.interactions.create(
        model=model,
        input=prompt,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": EnrichedCsv.model_json_schema(),
        },
    )
    return EnrichedCsv.model_validate_json(response.output_text)


def validate_enriched_rows(
    source_rows: list[dict[str, str]],
    enriched_rows: list[EnrichedWordRow],
) -> None:
    if len(source_rows) != len(enriched_rows):
        raise EnrichmentError(
            f"Gemini returned {len(enriched_rows)} rows for {len(source_rows)} input rows"
        )

    for index, (source, enriched) in enumerate(
        zip(source_rows, enriched_rows, strict=True),
        start=2,
    ):
        enriched_data = enriched.model_dump()
        for column in INPUT_COLUMNS:
            if enriched_data[column] != source[column]:
                raise EnrichmentError(
                    f"Gemini changed {column!r} on CSV row {index}: "
                    f"{source[column]!r} -> {enriched_data[column]!r}"
                )


def write_enriched_csv(path: Path, rows: list[EnrichedWordRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=OUTPUT_COLUMNS,
            delimiter="|",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row.model_dump())


def iter_input_words(input_dir: Path) -> list[str]:
    if not input_dir.exists():
        raise EnrichmentError(f"{input_dir} does not exist")
    if not input_dir.is_dir():
        raise EnrichmentError(f"{input_dir} is not a directory")

    words = sorted(path.stem for path in input_dir.glob("*.csv") if path.is_file())
    if not words:
        raise EnrichmentError(f"{input_dir} contains no CSV files")
    return words


def enrich_word(args: argparse.Namespace, api_key: str, prompt_text: str, word: str) -> Path:
    input_path = args.input_dir / f"{word}.csv"
    output_path = args.output_dir / f"{word}_enriched.csv"
    if output_path.exists() and not args.overwrite:
        tqdm.write(f"Skipping {word}: {output_path} already exists")
        return output_path

    fieldnames, source_rows = read_csv(input_path)
    csv_text = rows_to_pipe_csv(fieldnames, source_rows)
    prompt = build_prompt(prompt_text, input_path.name, csv_text)

    enriched = enrich_with_gemini(api_key=api_key, model=args.model, prompt=prompt)
    validate_enriched_rows(source_rows, enriched.rows)
    write_enriched_csv(output_path, enriched.rows)
    print(f"Wrote {output_path} ({len(enriched.rows)} rows)")
    return output_path


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    load_dotenv(args.env_file)

    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        raise EnrichmentError(
            f"{API_KEY_ENV} is not set. Export it or add it to {args.env_file}."
        )

    prompt_text = args.prompt.read_text(encoding="utf-8")
    if args.word:
        enrich_word(args, api_key, prompt_text, args.word)
        return 0

    failed_words: list[str] = []
    words = iter_input_words(args.input_dir)
    for word in tqdm(words, desc="Enriching words", unit="word"):
        try:
            enrich_word(args, api_key, prompt_text, word)
        except (OSError, ValidationError, EnrichmentError) as exc:
            failed_words.append(word)
            tqdm.write(f"Skipping {word}: {exc}")

    if failed_words:
        print(f"Skipped {len(failed_words)} word(s) with errors: {', '.join(failed_words)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (OSError, ValidationError, EnrichmentError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
