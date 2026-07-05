#!/usr/bin/env python3
"""Generate, enrich, publish, and categorize one German word family."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_ASSETS_DIR = Path("assets")
DEFAULT_ENV_FILE = Path(".env")
DEFAULT_GENERATED_DIR = Path("data/3_output")
DEFAULT_ENRICHED_DIR = Path("data/4_enriched_gemini")
DEFAULT_MODEL = "gemini-3.5-flash"
API_KEY_ENV = "GOOGLE_GEMINI_API_KEY"


class WorkflowError(RuntimeError):
    """Raised when the word-family workflow cannot finish."""


CATEGORY_CHOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "category_id": {
            "type": "string",
            "description": "One exact category key from the allowed list.",
        },
    },
    "required": ["category_id"],
    "additionalProperties": False,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a Wiktionary word-family CSV, enrich it with Gemini, copy the "
            "enriched CSV into assets/enriched, and add it to assets/verbs.json."
        )
    )
    parser.add_argument("word", help='German base word, for example "weisen".')
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root. Defaults to the parent of this script directory.",
    )
    parser.add_argument(
        "--generated-dir",
        type=Path,
        default=DEFAULT_GENERATED_DIR,
        help=f"Directory for Wiktionary CSVs (default: {DEFAULT_GENERATED_DIR})",
    )
    parser.add_argument(
        "--enriched-dir",
        type=Path,
        default=DEFAULT_ENRICHED_DIR,
        help=f"Directory for Gemini-enriched CSVs (default: {DEFAULT_ENRICHED_DIR})",
    )
    parser.add_argument(
        "--assets-dir",
        type=Path,
        default=DEFAULT_ASSETS_DIR,
        help=f"Assets directory to publish into (default: {DEFAULT_ASSETS_DIR})",
    )
    parser.add_argument(
        "--verbs-json",
        type=Path,
        default=DEFAULT_ASSETS_DIR / "verbs.json",
        help="Verb manifest to update (default: assets/verbs.json)",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help=f"Optional .env file for {API_KEY_ENV} (default: {DEFAULT_ENV_FILE})",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Gemini model for enrichment and classification (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--category",
        help="Skip Gemini classification and use this existing category key.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing enriched outputs and asset CSVs.",
    )
    return parser.parse_args(argv)


def repo_path(repo_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


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


def run_command(command: list[str], cwd: Path) -> None:
    print("$ " + " ".join(command))
    result = subprocess.run(command, cwd=cwd, check=False)
    if result.returncode != 0:
        raise WorkflowError(f"command failed with exit code {result.returncode}")


def run_wiktionary_script(
    repo_root: Path,
    word: str,
    generated_dir: Path,
) -> Path:
    output_path = generated_dir / f"{word}.csv"
    run_command(
        [
            sys.executable,
            str(repo_root / "scripts" / "wiktionary_unterbegriffe.py"),
            word,
            "--output",
            str(output_path),
        ],
        cwd=repo_root,
    )
    if not output_path.exists():
        raise WorkflowError(f"{output_path} was not created")
    return output_path


def run_enrichment_script(
    repo_root: Path,
    word: str,
    generated_dir: Path,
    enriched_dir: Path,
    env_file: Path,
    model: str,
    overwrite: bool,
) -> Path:
    command = [
        sys.executable,
        str(repo_root / "scripts" / "enrich_csv_gemini.py"),
        word,
        "--input-dir",
        str(generated_dir),
        "--output-dir",
        str(enriched_dir),
        "--env-file",
        str(env_file),
        "--model",
        model,
    ]
    if overwrite:
        command.append("--overwrite")

    run_command(command, cwd=repo_root)

    output_path = enriched_dir / f"{word}_enriched.csv"
    if not output_path.exists():
        raise WorkflowError(f"{output_path} was not created")
    return output_path


def load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise WorkflowError(f"failed to read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"{path} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise WorkflowError(f"{path} must contain a category object")
    return data


def category_summary(manifest: dict[str, dict[str, Any]]) -> str:
    lines: list[str] = []
    for key, category in manifest.items():
        lines.append(
            "- "
            f"{key}: "
            f"{category.get('category_name_de', '')} / "
            f"{category.get('category_name_en', '')} / "
            f"{category.get('category_name_ru', '')}"
        )
    return "\n".join(lines)


def sample_words(path: Path, limit: int = 20) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="|")
        words = [
            (row.get("word") or "").strip()
            for row in reader
            if (row.get("word") or "").strip()
        ]
    return words[:limit]


def classify_category(
    api_key: str,
    model: str,
    word: str,
    related_words: list[str],
    manifest: dict[str, dict[str, Any]],
) -> str:
    from google import genai

    prompt = (
        "Classify one German base verb into exactly one existing semantic category "
        "for a vocabulary-learning app.\n\n"
        "Allowed categories:\n"
        f"{category_summary(manifest)}\n\n"
        f"German base word: {word}\n"
        f"Generated word-family terms: {', '.join(related_words)}\n\n"
        "Return JSON only. The category_id must be one exact key from the allowed "
        "categories. Prefer the main verb meaning over rare derived meanings."
    )

    client = genai.Client(api_key=api_key)
    response = client.interactions.create(
        model=model,
        input=prompt,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": CATEGORY_CHOICE_SCHEMA,
        },
    )
    try:
        choice = json.loads(response.output_text)
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"Gemini returned invalid JSON: {exc}") from exc

    category_id = choice.get("category_id") if isinstance(choice, dict) else None
    if not isinstance(category_id, str):
        raise WorkflowError("Gemini response did not include a string category_id")
    if category_id not in manifest:
        allowed = ", ".join(manifest.keys())
        raise WorkflowError(
            f"Gemini returned unknown category {category_id!r}; allowed: {allowed}"
        )
    return category_id


def publish_enriched_csv(
    source_path: Path,
    assets_dir: Path,
    word: str,
    overwrite: bool,
) -> Path:
    destination = assets_dir / "enriched" / f"{word}_enriched.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)

    if destination.exists() and not overwrite:
        if destination.read_bytes() == source_path.read_bytes():
            return destination
        raise WorkflowError(
            f"{destination} already exists and differs from {source_path}; use --overwrite"
        )

    shutil.copy2(source_path, destination)
    return destination


def manifest_entry(word: str) -> dict[str, str]:
    return {
        "base": word,
        "label": word,
        "enriched": f"assets/enriched/{word}_enriched.csv",
    }


def update_manifest(
    manifest: dict[str, dict[str, Any]],
    category_id: str,
    word: str,
) -> bool:
    new_entry = manifest_entry(word)
    changed = False

    for category in manifest.values():
        words = category.get("words")
        if not isinstance(words, list):
            continue
        for entry in words:
            if not isinstance(entry, dict):
                continue
            if entry.get("base") == word:
                if entry != new_entry:
                    entry.clear()
                    entry.update(new_entry)
                    changed = True
                return changed

    category = manifest[category_id]
    words = category.setdefault("words", [])
    if not isinstance(words, list):
        raise WorkflowError(f"category {category_id!r} has non-list words value")

    words.append(new_entry)
    words.sort(key=lambda entry: (entry.get("label") or entry.get("base") or "").casefold())
    return True


def write_manifest(path: Path, manifest: dict[str, dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    word = args.word.strip()
    if not word:
        raise WorkflowError("word must not be empty")

    repo_root = args.repo_root.resolve()
    generated_dir = repo_path(repo_root, args.generated_dir)
    enriched_dir = repo_path(repo_root, args.enriched_dir)
    assets_dir = repo_path(repo_root, args.assets_dir)
    verbs_json = repo_path(repo_root, args.verbs_json)
    env_file = repo_path(repo_root, args.env_file)

    load_dotenv(env_file)
    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        raise WorkflowError(f"{API_KEY_ENV} is not set. Export it or add it to {env_file}.")

    manifest = load_manifest(verbs_json)
    if args.category and args.category not in manifest:
        allowed = ", ".join(manifest.keys())
        raise WorkflowError(f"unknown category {args.category!r}; allowed: {allowed}")

    generated_path = run_wiktionary_script(repo_root, word, generated_dir)
    enriched_path = run_enrichment_script(
        repo_root,
        word,
        generated_dir,
        enriched_dir,
        env_file,
        args.model,
        args.overwrite,
    )

    category_id = args.category or classify_category(
        api_key=api_key,
        model=args.model,
        word=word,
        related_words=sample_words(generated_path),
        manifest=manifest,
    )
    published_path = publish_enriched_csv(
        source_path=enriched_path,
        assets_dir=assets_dir,
        word=word,
        overwrite=args.overwrite,
    )
    changed = update_manifest(manifest, category_id, word)
    if changed:
        write_manifest(verbs_json, manifest)

    print(f"Generated: {generated_path}")
    print(f"Enriched: {enriched_path}")
    print(f"Published: {published_path}")
    print(f"Manifest category: {category_id}")
    print(f"Manifest updated: {'yes' if changed else 'already present'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, WorkflowError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
