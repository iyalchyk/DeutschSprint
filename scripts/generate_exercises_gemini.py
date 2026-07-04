#!/usr/bin/env python3
"""Generate exercise CSVs from Gemini-enriched word CSVs."""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Literal

from google import genai
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tqdm import tqdm


DEFAULT_INPUT_DIR = Path("data/4_enriched_gemini")
DEFAULT_OUTPUT_DIR = Path("data/5_exercises")
DEFAULT_PROMPT_PATH = Path("data/1_input/prompt_02.txt")
DEFAULT_ENV_FILE = Path(".env")
DEFAULT_MODEL = "gemini-3.5-flash"
API_KEY_ENV = "GOOGLE_GEMINI_API_KEY"

INPUT_COLUMNS = [
    "word_base",
    "word",
    "word_level",
    "word_freq",
    "word_translation_en",
    "word_translation_ru",
    "word_synonyms",
    "sentence_example",
    "sentence_example_translation_en",
    "sentence_example_translation_ru",
    "sentence_synonym",
]
OUTPUT_COLUMNS = [
    "exercise_id",
    "type",
    "word_base",
    "word",
    "word_level",
    "word_freq",
    "question",
    "correct_answer",
    "accepted_answers",
    "option_1",
    "option_2",
    "option_3",
    "option_4",
    "sentence_example",
    "sentence_example_translation_en",
    "sentence_example_translation_ru",
    "extra",
    "explanation",
]
CORE_EXERCISE_TYPES = [
    "multiple_choice_de_en",
    "multiple_choice_ru_de",
    "multiple_choice_synonym",
    "sentence_translation_de_en",
    "sentence_translation_de_ru",
    "sentence_order",
    "multiple_choice_sentence_paraphrase",
]
DERIVED_EXERCISE_TYPE = "word_family_base"
EXERCISE_TYPES = [*CORE_EXERCISE_TYPES, DERIVED_EXERCISE_TYPE]


class ExerciseRow(BaseModel):
    """One row in the generated exercise CSV."""

    model_config = ConfigDict(extra="forbid")

    exercise_id: str
    type: Literal[
        "multiple_choice_de_en",
        "multiple_choice_ru_de",
        "multiple_choice_synonym",
        "sentence_translation_de_en",
        "sentence_translation_de_ru",
        "sentence_order",
        "multiple_choice_sentence_paraphrase",
        "word_family_base",
    ]
    word_base: str
    word: str
    word_level: str
    word_freq: str
    question: str
    correct_answer: str
    accepted_answers: str
    option_1: str = ""
    option_2: str = ""
    option_3: str = ""
    option_4: str = ""
    sentence_example: str
    sentence_example_translation_en: str
    sentence_example_translation_ru: str
    extra: str = ""
    explanation: str


class ExerciseCsv(BaseModel):
    """Complete exercise CSV payload returned by Gemini."""

    model_config = ConfigDict(extra="forbid")

    rows: list[ExerciseRow] = Field(
        description="Rows in exercise_id order for the complete output CSV."
    )


class ExerciseGenerationError(RuntimeError):
    """Raised when exercise generation cannot be completed."""


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Load Gemini-enriched CSV files and generate universal exercise CSVs. "
            "If INPUT is omitted, all *_enriched.csv files in --input-dir are processed."
        )
    )
    parser.add_argument(
        "input",
        nargs="?",
        help=(
            "Enriched CSV path or base word, e.g. weisen. If omitted, process all "
            "CSV files in --input-dir."
        ),
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Directory containing <word>_enriched.csv files (default: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for exercise CSV files (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output file path for a single input file.",
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


def read_enriched_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file, delimiter="|")
        rows = list(reader)

    fieldnames = reader.fieldnames or []
    missing_columns = [column for column in INPUT_COLUMNS if column not in fieldnames]
    if missing_columns:
        raise ExerciseGenerationError(
            f"{path} is missing required columns: {', '.join(missing_columns)}"
        )
    if not rows:
        raise ExerciseGenerationError(f"{path} has no data rows")
    return fieldnames, rows


def rows_to_pipe_csv(fieldnames: list[str], rows: list[dict[str, str]]) -> str:
    lines = ["|".join(fieldnames)]
    for row in rows:
        lines.append("|".join(row.get(field, "") for field in fieldnames))
    return "\n".join(lines)


def output_base_name(input_path: Path) -> str:
    stem = input_path.stem
    if stem.endswith("_enriched"):
        return stem[: -len("_enriched")]
    return stem


def output_path_for(input_path: Path, args: argparse.Namespace) -> Path:
    if args.output:
        return args.output
    return args.output_dir / f"{output_base_name(input_path)}_exercises_universal.csv"


def build_prompt(prompt_text: str, input_filename: str, csv_text: str) -> str:
    return (
        f"{prompt_text.strip()}\n\n"
        f"INPUT_FILENAME: {input_filename}\n\n"
        "Return JSON that conforms to the provided response schema. "
        "Do not return Markdown or a raw CSV. "
        "Generate rows for a CSV with exactly these columns, in this order: "
        f"{', '.join(OUTPUT_COLUMNS)}. "
        "For each input row, create the seven core exercise types in this exact order: "
        f"{', '.join(CORE_EXERCISE_TYPES)}. "
        "If word differs from word_base, add one word_family_base exercise after those "
        "seven rows. Keep exercise_id sequential as <word_base>_001, <word_base>_002, "
        "and so on. Preserve word_base, word, word_level, word_freq, sentence_example, "
        "sentence_example_translation_en, and sentence_example_translation_ru exactly "
        "from the input row. Use Russian for question and explanation, matching the "
        "style of the examples. Do not use newline characters inside field values. "
        "Use pipe characters only inside accepted_answers and sentence_order extra.\n\n"
        "Input pipe-separated enriched CSV:\n"
        f"{csv_text}\n"
    )


def generate_with_gemini(api_key: str, model: str, prompt: str) -> ExerciseCsv:
    client = genai.Client(api_key=api_key)
    response = client.interactions.create(
        model=model,
        input=prompt,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": ExerciseCsv.model_json_schema(),
        },
    )
    return ExerciseCsv.model_validate_json(response.output_text)


def expected_exercise_types(rows: list[dict[str, str]]) -> list[str]:
    expected: list[str] = []
    for row in rows:
        expected.extend(CORE_EXERCISE_TYPES)
        if row["word"] != row["word_base"]:
            expected.append(DERIVED_EXERCISE_TYPE)
    return expected


def validate_no_newlines(exercise: ExerciseRow, index: int) -> None:
    for column, value in exercise.model_dump().items():
        if "\n" in value or "\r" in value:
            raise ExerciseGenerationError(
                f"Gemini returned a newline in {column!r} on exercise row {index}"
            )


def validate_options(exercise: ExerciseRow, index: int) -> None:
    options = [
        exercise.option_1,
        exercise.option_2,
        exercise.option_3,
        exercise.option_4,
    ]
    has_options = any(options)
    needs_options = exercise.type.startswith("multiple_choice") or (
        exercise.type == DERIVED_EXERCISE_TYPE
    )
    if needs_options and not all(options):
        raise ExerciseGenerationError(
            f"Gemini returned incomplete options on exercise row {index}"
        )
    if needs_options and exercise.correct_answer not in options:
        raise ExerciseGenerationError(
            f"correct_answer is not one of the options on exercise row {index}"
        )
    if not needs_options and has_options:
        raise ExerciseGenerationError(
            f"Gemini returned options for non-choice exercise row {index}"
        )


def validate_exercises(
    source_rows: list[dict[str, str]],
    exercise_rows: list[ExerciseRow],
) -> None:
    expected_types = expected_exercise_types(source_rows)
    if len(exercise_rows) != len(expected_types):
        raise ExerciseGenerationError(
            f"Gemini returned {len(exercise_rows)} exercises; expected {len(expected_types)}"
        )

    source_index = 0
    type_index_for_source = 0
    for index, (exercise, expected_type) in enumerate(
        zip(exercise_rows, expected_types, strict=True),
        start=1,
    ):
        validate_no_newlines(exercise, index)
        validate_options(exercise, index)

        expected_id = f"{source_rows[0]['word_base']}_{index:03d}"
        if exercise.exercise_id != expected_id:
            raise ExerciseGenerationError(
                f"Gemini returned exercise_id {exercise.exercise_id!r}; "
                f"expected {expected_id!r}"
            )
        if exercise.type != expected_type:
            raise ExerciseGenerationError(
                f"Gemini returned exercise type {exercise.type!r} on exercise row {index}; "
                f"expected {expected_type!r}"
            )

        source = source_rows[source_index]
        exercise_data = exercise.model_dump()
        for column in [
            "word_base",
            "word",
            "word_level",
            "word_freq",
            "sentence_example",
            "sentence_example_translation_en",
            "sentence_example_translation_ru",
        ]:
            if exercise_data[column] != source[column]:
                raise ExerciseGenerationError(
                    f"Gemini changed {column!r} on exercise row {index}: "
                    f"{source[column]!r} -> {exercise_data[column]!r}"
                )

        type_index_for_source += 1
        expected_count_for_source = len(CORE_EXERCISE_TYPES)
        if source["word"] != source["word_base"]:
            expected_count_for_source += 1
        if type_index_for_source == expected_count_for_source:
            source_index += 1
            type_index_for_source = 0


def write_exercise_csv(path: Path, rows: list[ExerciseRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=OUTPUT_COLUMNS,
            delimiter=",",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row.model_dump())


def resolve_input_path(input_value: str, input_dir: Path) -> Path:
    candidate = Path(input_value)
    if candidate.exists():
        return candidate

    if candidate.suffix == ".csv":
        input_dir_candidate = input_dir / candidate.name
        if input_dir_candidate.exists():
            return input_dir_candidate
        return candidate

    return input_dir / f"{input_value}_enriched.csv"


def iter_input_paths(input_dir: Path) -> list[Path]:
    if not input_dir.exists():
        raise ExerciseGenerationError(f"{input_dir} does not exist")
    if not input_dir.is_dir():
        raise ExerciseGenerationError(f"{input_dir} is not a directory")

    paths = sorted(path for path in input_dir.glob("*_enriched.csv") if path.is_file())
    if not paths:
        paths = sorted(path for path in input_dir.glob("*.csv") if path.is_file())
    if not paths:
        raise ExerciseGenerationError(f"{input_dir} contains no CSV files")
    return paths


def generate_for_file(
    args: argparse.Namespace,
    api_key: str,
    prompt_text: str,
    input_path: Path,
) -> Path:
    output_path = output_path_for(input_path, args)
    if output_path.exists() and not args.overwrite:
        tqdm.write(f"Skipping {input_path.name}: {output_path} already exists")
        return output_path

    fieldnames, source_rows = read_enriched_csv(input_path)
    csv_text = rows_to_pipe_csv(fieldnames, source_rows)
    prompt = build_prompt(prompt_text, input_path.name, csv_text)

    exercises = generate_with_gemini(api_key=api_key, model=args.model, prompt=prompt)
    validate_exercises(source_rows, exercises.rows)
    write_exercise_csv(output_path, exercises.rows)
    print(f"Wrote {output_path} ({len(exercises.rows)} rows)")
    return output_path


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.output and not args.input:
        raise ExerciseGenerationError("--output can only be used with a single input file")

    load_dotenv(args.env_file)
    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        raise ExerciseGenerationError(
            f"{API_KEY_ENV} is not set. Export it or add it to {args.env_file}."
        )

    prompt_text = args.prompt.read_text(encoding="utf-8")
    if args.input:
        input_path = resolve_input_path(args.input, args.input_dir)
        generate_for_file(args, api_key, prompt_text, input_path)
        return 0

    failed_inputs: list[str] = []
    input_paths = iter_input_paths(args.input_dir)
    for input_path in tqdm(input_paths, desc="Generating exercises", unit="file"):
        try:
            generate_for_file(args, api_key, prompt_text, input_path)
        except (OSError, ValidationError, ExerciseGenerationError) as exc:
            failed_inputs.append(input_path.name)
            tqdm.write(f"Skipping {input_path.name}: {exc}")

    if failed_inputs:
        print(
            f"Skipped {len(failed_inputs)} file(s) with errors: "
            f"{', '.join(failed_inputs)}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (OSError, ValidationError, ExerciseGenerationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
