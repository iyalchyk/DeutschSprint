#!/usr/bin/env python3
"""Enrich a word CSV with Gemini and write a pipe-separated CSV."""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import tempfile
import time
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from google import genai
from google.genai import errors as genai_errors
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tqdm import tqdm


DEFAULT_INPUT_DIR = Path("data/3_output")
DEFAULT_OUTPUT_DIR = Path("data/4_enriched_gemini")
DEFAULT_PROMPT_PATH = Path("data/1_input/prompt_01.txt")
DEFAULT_ENV_FILE = Path(".env")
DEFAULT_MODEL = "gemini-3.8-flash"
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


class EnrichmentRequestError(EnrichmentError):
    """Normalize errors from both versions of the Gemini SDK transport."""

    def __init__(self, message: str, retryable: bool, retry_after_seconds: float = 0):
        super().__init__(message)
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


class EnrichmentQuotaError(EnrichmentRequestError):
    """A daily quota needs a reset or a different model, not immediate retries."""


class PartialEnrichmentError(EnrichmentError):
    """Preserve valid rows without resending them because another row failed."""

    def __init__(self, rows: list[EnrichedWordRow], missing: list[str]):
        super().__init__(f"{len(rows)} valid rows; {len(missing)} words need another attempt")
        self.rows = rows
        self.missing = missing


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Load data/3_output/<word>.csv files, enrich them with Gemini, and write "
            "a dated data/4_enriched_gemini_YYYYMMDD directory."
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
        default=DEFAULT_OUTPUT_DIR.with_name(f"{DEFAULT_OUTPUT_DIR.name}_{date.today():%Y%m%d}"),
        help="Output directory (default: data/4_enriched_gemini_YYYYMMDD)",
    )
    parser.add_argument(
        "--cache-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
        help=f"Directory of existing enrichments (default: {DEFAULT_OUTPUT_DIR})",
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
        help="Regenerate enrichment, including words already present in outputs.",
    )
    parser.add_argument("--batch-size", type=int, default=20,
                        help="Maximum new words per Gemini request (default: 20).")
    parser.add_argument("--workers", type=int, default=1,
                        help="Concurrent Gemini requests (default: 1).")
    parser.add_argument("--request-timeout", type=float, default=180,
                        help="Request timeout in seconds; increase for large batches (default: 180).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report missing and reusable words without API calls or writes.")
    args = parser.parse_args(argv)
    if args.batch_size < 1 or args.workers < 1 or args.request_timeout <= 0:
        parser.error("--batch-size, --workers and --request-timeout must be positive")
    return args


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
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, delimiter="|",
                            lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


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


def enrich_with_gemini(api_key: str, model: str, prompt: str, request_timeout: float = 180) -> EnrichedCsv:
    # Bound requests and handle retries here rather than stacking SDK retries.
    client = genai.Client(api_key=api_key, http_options={
        "timeout": int(request_timeout * 1000), "retry_options": {"attempts": 1},
    })
    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_json_schema": EnrichedCsv.model_json_schema(),
                "thinking_config": {"thinking_level": "LOW"},
                "max_output_tokens": 65536,
            },
        )
    except Exception as exc:
        status = getattr(exc, "status_code", getattr(exc, "code", None))
        if status == 429 and "RequestsPerDay" in str(exc):
            raise EnrichmentQuotaError(str(exc), retryable=False) from exc
        raise EnrichmentRequestError(
            str(exc), retryable=status in {None, 408, 429, 500, 502, 503, 504},
            retry_after_seconds=30 if status == 503 else 0,
        ) from exc
    finally:
        client.close()
    return EnrichedCsv.model_validate_json(response.text)


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
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="",
                                         dir=path.parent, delete=False) as file:
            temporary_path = Path(file.name)
            writer = csv.DictWriter(file, fieldnames=OUTPUT_COLUMNS, delimiter="|",
                                    lineterminator="\n", extrasaction="ignore")
            writer.writeheader()
            writer.writerows(row.model_dump() for row in rows)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def iter_input_words(input_dir: Path) -> list[str]:
    if not input_dir.exists():
        raise EnrichmentError(f"{input_dir} does not exist")
    if not input_dir.is_dir():
        raise EnrichmentError(f"{input_dir} is not a directory")

    words = sorted(path.stem for path in input_dir.glob("*.csv") if path.is_file())
    if not words:
        raise EnrichmentError(f"{input_dir} contains no CSV files")
    return words


def output_path_for_word(output_dir: Path, word: str) -> Path:
    return output_dir / f"{word}_enriched.csv"


def load_existing_rows(path: Path) -> dict[str, EnrichedWordRow]:
    """Reuse complete rows only; preserve German noun/verb capitalization."""
    if not path.exists():
        return {}
    _, rows = read_csv(path)
    result = {}
    for row in rows:
        try:
            enriched = EnrichedWordRow.model_validate(row)
        except ValidationError:
            continue
        if all(enriched.model_dump()[column].strip() for column in ENRICHED_COLUMNS):
            result[enriched.word] = enriched
    return result


def pending_input_words(args: argparse.Namespace, words: list[str]) -> list[str]:
    """An existing file can still have missing or incomplete word rows."""
    if args.overwrite:
        return words
    pending = []
    for word in words:
        _, source_rows = read_csv(args.input_dir / f"{word}.csv")
        existing = load_existing_rows(output_path_for_word(args.output_dir, word))
        if any(row["word"] not in existing for row in source_rows):
            pending.append(word)
    return pending


def enrich_batch(
    api_key: str, model: str, prompt_text: str, rows: list[dict[str, str]],
    request_timeout: float = 180,
) -> list[EnrichedWordRow]:
    prompt = build_prompt(prompt_text, "new_words.csv", rows_to_pipe_csv(INPUT_COLUMNS, rows))
    for attempt in range(3):
        retry_delay = 2 ** (attempt + 1)
        try:
            enriched = enrich_with_gemini(api_key=api_key, model=model, prompt=prompt,
                                          request_timeout=request_timeout)
            expected = {row["word"]: row for row in rows}
            valid = {}
            for row in enriched.rows:
                source = expected.get(row.word)
                if source is None or row.word in valid:
                    continue
                try:
                    validate_enriched_rows([source], [row])
                except EnrichmentError:
                    continue
                if all(row.model_dump()[column].strip() for column in ENRICHED_COLUMNS):
                    valid[row.word] = row
            ordered = [valid[row["word"]] for row in rows if row["word"] in valid]
            missing = [row["word"] for row in rows if row["word"] not in valid]
            if missing:
                raise PartialEnrichmentError(ordered, missing)
            return ordered
        except PartialEnrichmentError:
            raise
        except EnrichmentRequestError as exc:
            if not exc.retryable or attempt == 2:
                raise
            tqdm.write(f"Retrying {len(rows)} words after request attempt {attempt + 1}: {exc}")
            retry_delay = max(retry_delay, exc.retry_after_seconds * (attempt + 1))
        except genai_errors.APIError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise
        except (OSError, ValidationError, EnrichmentError):
            if attempt == 2:
                raise
            tqdm.write(f"Retrying {len(rows)} words after invalid response {attempt + 1}")
        time.sleep(retry_delay)
    raise EnrichmentError("Enrichment retries exhausted")


def run_enrichment(args: argparse.Namespace, words: list[str]) -> int:
    sources = {}
    own_rows = {}
    cache = {}
    if not args.overwrite:
        # Reuse a word enriched in any family, without paying for it a second time.
        for directory in (args.output_dir, args.cache_dir):
            for path in sorted(directory.glob("*.csv")):
                for word, row in load_existing_rows(path).items():
                    cache.setdefault(word, row)
    for base in words:
        _, rows = read_csv(args.input_dir / f"{base}.csv")
        sources[base] = [{column: row[column] for column in INPUT_COLUMNS} for row in rows]
        own_rows[base] = {}
        if not args.overwrite:
            for path in (output_path_for_word(args.output_dir, base),
                         output_path_for_word(args.cache_dir, base),
                         args.cache_dir / f"{base}.csv"):
                for word, row in load_existing_rows(path).items():
                    own_rows[base].setdefault(word, row)

    new_words = {}
    retained_count = reused_count = 0
    for base, rows in sources.items():
        for row in rows:
            word = row["word"]
            if word in own_rows[base]:
                retained_count += 1
            elif word in cache:
                reused_count += 1
            else:
                new_words.setdefault(word, row)
    print(f"Input: {sum(map(len, sources.values()))} rows in {len(words)} files; "
          f"keeping {retained_count} existing rows; reusing {reused_count} rows "
          f"from other families; {len(new_words)} unique new words", flush=True)
    if args.dry_run:
        return 0

    # Validate configuration before changing outputs when requests are needed.
    api_key = ""
    prompt_text = ""
    if new_words:
        load_dotenv(args.env_file)
        api_key = os.environ.get(API_KEY_ENV, "")
        if not api_key:
            raise EnrichmentError(
                f"{API_KEY_ENV} is not set. Export it or add it to {args.env_file}."
            )
        prompt_text = args.prompt.read_text(encoding="utf-8")

    def checkpoint(bases: list[str]) -> None:
        for base in bases:
            merged = []
            for source in sources[base]:
                existing = own_rows[base].get(source["word"]) or cache.get(source["word"])
                if existing is not None:
                    # Current input controls metadata; existing enrichment stays intact.
                    merged.append(existing.model_copy(update=source))
            path = output_path_for_word(args.output_dir, base)
            if not merged:
                continue
            serialized = rows_to_pipe_csv(OUTPUT_COLUMNS, [row.model_dump() for row in merged])
            if not path.exists() or path.read_text(encoding="utf-8") != serialized:
                write_enriched_csv(path, merged)

    checkpoint(words)
    if not new_words:
        print("No words need Gemini enrichment", flush=True)
        return 0

    dependents = {}
    for base, rows in sources.items():
        for row in rows:
            dependents.setdefault(row["word"], set()).add(base)
    pending = list(new_words.values())
    batches = [pending[index:index + args.batch_size]
               for index in range(0, len(pending), args.batch_size)]
    failures = []
    completed_words = 0
    def record_batch(enriched: list[EnrichedWordRow]) -> None:
        nonlocal completed_words
        affected = set()
        for row in enriched:
            cache[row.word] = row
            affected.update(dependents[row.word])
        checkpoint(sorted(affected))
        completed_words += len(enriched)
        tqdm.write(f"Checkpointed {completed_words}/{len(pending)} new words")

    # Check one real request before scheduling the rest (e.g. bad model/key).
    try:
        record_batch(enrich_batch(api_key, args.model, prompt_text, batches[0],
                                  request_timeout=args.request_timeout))
    except PartialEnrichmentError as exc:
        record_batch(exc.rows)
        failures.extend(exc.missing)
        tqdm.write(str(exc))
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        jobs = {executor.submit(enrich_batch, api_key, args.model, prompt_text, batch,
                                request_timeout=args.request_timeout): batch
                for batch in batches[1:]}
        for future in tqdm(as_completed(jobs), total=len(jobs), desc="Enriching new words",
                           unit="batch"):
            batch = jobs[future]
            if future.cancelled():
                failures.extend(row["word"] for row in batch)
                continue
            try:
                enriched = future.result()
            except PartialEnrichmentError as exc:
                record_batch(exc.rows)
                failures.extend(exc.missing)
                tqdm.write(str(exc))
                continue
            except (genai_errors.APIError, OSError, ValidationError, EnrichmentError) as exc:
                failures.extend(row["word"] for row in batch)
                tqdm.write(f"Failed batch ({len(batch)} words): {exc}")
                if isinstance(exc, EnrichmentQuotaError):
                    for job in jobs:
                        job.cancel()
                continue
            record_batch(enriched)
    if failures:
        print(f"{len(failures)} words still need enrichment: {', '.join(failures)}", flush=True)
        return 1
    print(f"Enriched {completed_words} unique new words; synchronized {len(words)} files", flush=True)
    return 0


def enrich_word(args: argparse.Namespace, api_key: str, prompt_text: str, word: str) -> Path:
    """Compatibility entry point; the incremental path is shared with batch runs."""
    os.environ[API_KEY_ENV] = api_key
    if run_enrichment(args, [word]):
        raise EnrichmentError(f"Some words in {word!r} still need enrichment")
    return output_path_for_word(args.output_dir, word)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    words = [args.word] if args.word else iter_input_words(args.input_dir)
    return run_enrichment(args, words)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (genai_errors.APIError, OSError, ValidationError, EnrichmentError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
