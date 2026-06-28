# DeutschSprint

## Wiktionary Unterbegriffe export

Generate a pipe-separated CSV for a German base word:

```sh
python3 scripts/wiktionary_unterbegriffe.py lassen
```

By default this writes `data/3_output/lassen.csv`.

The output columns are:

```text
word_base|word|word_level|word_freq
```

By default the script queries:

- German Wiktionary for `Unterbegriffe`, falling back to `Wortbildungen`.
- `data/2_interim/german_frequency_join.csv` for CEFR levels from
  `german_api_level`.
- `data/2_interim/german_frequency_join.csv` for word frequency from
  `dwds_freq`.

If a word is missing from the CEFR source, the script estimates a level from
its frequency rank. Use `--no-infer-level` to leave unmatched levels blank.

You can point the CEFR or frequency lookups at another open CSV/TSV source:

```sh
python3 scripts/wiktionary_unterbegriffe.py lassen \
  --level-source path-or-url/to/levels.tsv \
  --frequency-source path-or-url/to/frequencies.txt \
  -o assets/lassen.csv
```

## German API dump

Dump the German vocabulary API into per-page JSON files plus one combined file:

```sh
python3 scripts/german_api_dump.py
```

This writes page files such as `data/1_input/GermanAPI/german_api_a1_p01.json`
and a combined file at `data/1_input/GermanAPI/german_api_all_levels.json`.
