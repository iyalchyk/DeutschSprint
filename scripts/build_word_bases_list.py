#!/usr/bin/env python3
"""Merge word-base text files into one deduplicated output list."""

from __future__ import annotations

from pathlib import Path


INPUT_FILES = [
    Path("data/1_input/word_bases_list_01.txt"),
    Path("data/1_input/word_bases_list_02.txt"),
]
OUTPUT_FILE = Path("data/2_interim/word_bases_list.txt")


def load_words(paths: list[Path]) -> set[str]:
    words: set[str] = set()

    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                word = line.strip()
                if word:
                    words.add(word)

    return words


def main() -> int:
    words = load_words(INPUT_FILES)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text("\n".join(sorted(words)) + "\n", encoding="utf-8")
    print(f"Wrote {len(words)} words to {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
