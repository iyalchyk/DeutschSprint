# DeutschSprint

DeutschSprint builds German vocabulary data in three stages:

1. Fetch CEFR-tagged vocabulary from the German API.
2. Join that data with DWDS and DeReKo frequency sources.
3. Fetch Wiktionary `Unterbegriffe` / `Wortbildungen` for each base word.

The scripts are standalone Python CLI tools and use only the standard library.

## Requirements

- Python `>=3.14` as declared in [pyproject.toml](/Users/iyalchyk/@projects/DeutschSprint/pyproject.toml)
- Network access for:
  - `scripts/german_api_dump.py`
  - `scripts/wiktionary_unterbegriffe.py`

## Data Flow

- Input data lives under `data/1_input/`
- Joined intermediate data is written to `data/2_interim/`
- Final per-word outputs are written to `data/3_output/`

The default pipeline output files are:

- `data/1_input/GermanAPI/german_api_all_levels.json`
- `data/2_interim/german_frequency_join.csv`
- `data/3_output/<word>.csv`

## Script Usage

### 1. Fetch German API data

Run [scripts/german_api_dump.py](/Users/iyalchyk/@projects/DeutschSprint/scripts/german_api_dump.py) first.

It fetches paginated German vocabulary data for CEFR levels `A1 A2 B1 B2 C1`, writes one JSON file per page, and also writes a combined file used by the next step.

```bash
python3 scripts/german_api_dump.py
```

Default output:

- `data/1_input/GermanAPI/german_api_<level>_pNN.json`
- `data/1_input/GermanAPI/german_api_all_levels.json`

Useful options:

- `--api-key` to override the API key
- `--output-dir` to change the destination directory
- `--levels` to restrict the CEFR levels fetched
- `--limit` to change page size

It also reads `GERMAN_LANGUAGE_API_KEY` from the environment if set.

Example:

```bash
GERMAN_LANGUAGE_API_KEY=your-key python3 scripts/german_api_dump.py --levels A1 A2 B1
```

### 2. Build the joined frequency CSV

Run [scripts/build_frequency_csv.py](/Users/iyalchyk/@projects/DeutschSprint/scripts/build_frequency_csv.py) second.

It combines:

- DeReKo frequencies
- DWDS frequency data
- the combined German API JSON from step 1

Use the files already present in `data/1_input/`:

```bash
python3 scripts/build_frequency_csv.py \
  "data/1_input/DeReKo-2014-II-MainArchive-STT.100000.freq/DeReKo-2014-II-MainArchive-STT.100000.freq" \
  "data/1_input/DWDS Frequency -Frequenzbarometer- (Deu-Deu)/DWDS Frequency -Frequenzbarometer- (Deu-Deu).txt" \
  "data/1_input/GermanAPI/german_api_all_levels.json"
```

Default output:

- `data/2_interim/german_frequency_join.csv`

Useful option:

- `--output` to write the joined CSV somewhere else

### 3. Export Wiktionary terms for each base word

Run [scripts/wiktionary_unterbegriffe.py](/Users/iyalchyk/@projects/DeutschSprint/scripts/wiktionary_unterbegriffe.py) last, once per base word.

The script:

- fetches the German Wiktionary page for a word
- combines `Unterbegriffe` and `Wortbildungen`, keeping lowercase terms formed from a listed verb prefix or particle followed by the base word, and removing duplicates
- adds verbs matching the same prefix rule and tagged in DeReKo or GermanAPI and present in the frequency data; DWDS itself has no part-of-speech tags
- looks up CEFR level from `data/2_interim/german_frequency_join.csv`
- looks up frequency from the same joined CSV
- writes a pipe-separated CSV only when at least one derived word is found; removes a previous output for that base otherwise

Single-word example:

```bash
python3 scripts/wiktionary_unterbegriffe.py weisen
```

Default output:

- `data/3_output/weisen.csv`

Useful options:

- `--level-source` to use a different CEFR source
- `--frequency-source` to use a different frequency source
- `--no-infer-level` to leave missing levels blank
- `--limit` for smoke tests
- `--output` to override the destination path

### 4. Export standalone verbs

After building the joined frequency CSV and the family files, run:

```bash
python3 scripts/build_single_verbs.py
```

This writes `data/3_output/_single_verbs.csv` without network requests. It
collects single-word lowercase verb lemmas from DeReKo's verb tags and verb
entries from the German API, then removes every base and word already present
in a family CSV. It also excludes attested prefix-derived verbs and their
attested bases using a list of common German verb prefixes. This is a heuristic
and can miss unusual derivations or match unrelated words. It uses the joined
table and the same DWDS frequency and CEFR level lookup and inference as the family exporter; candidates without a DWDS
frequency are omitted. The result means “not present in the existing family
files,” not proof that a verb has no possible derivatives. Re-run after updating
family files or the joined data. Paths can be overridden using `--help`.

The pipe-separated output has columns `word_base|word|word_level|word_freq`;
`word_base` and `word` are identical in each row. Use `--dereko`, `--api`,
`--joined`, `--families`, or `--output` to override the default paths.

## Run The Full Workflow

Run the scripts in this order:

```bash
python3 scripts/german_api_dump.py

python3 scripts/build_frequency_csv.py \
  "data/1_input/DeReKo-2014-II-MainArchive-STT.100000.freq/DeReKo-2014-II-MainArchive-STT.100000.freq" \
  "data/1_input/DWDS Frequency -Frequenzbarometer- (Deu-Deu)/DWDS Frequency -Frequenzbarometer- (Deu-Deu).txt" \
  "data/1_input/GermanAPI/german_api_all_levels.json"
```

Then run the Wiktionary export for each word from [data/1_input/word_bases_list.txt](/Users/iyalchyk/@projects/DeutschSprint/data/1_input/word_bases_list.txt).

Example shell loop:

```bash
while IFS= read -r word; do
  case "$word" in
    ""|*:*|Word\ bases\ ultimate*)
      continue
      ;;
  esac
  python3 scripts/wiktionary_unterbegriffe.py "$word"
done < data/1_input/word_bases_list_01.txt
```

That skips empty lines and category headings such as `Движение и перемещение:`.

## Outputs

After the pipeline completes, you should have:

- raw German API dumps in `data/1_input/GermanAPI/`
- a joined metadata table at `data/2_interim/german_frequency_join.csv`
- one CSV per base word with at least one derived word in `data/3_output/`

You can also open [index.html](/Users/iyalchyk/@projects/DeutschSprint/index.html) in a browser to inspect the generated assets included in this repo.

## Incremental Gemini enrichment

After updating `data/3_output`, enrich new vocabulary with:

```bash
.venv/bin/python scripts/enrich_csv_gemini.py --workers 4 --batch-size 20
```

The script preserves complete existing enrichment, reuses words already enriched in other families, and sends only unique missing words to Gemini. German capitalization is significant, so a noun and a lowercase verb remain distinct. Current input rows determine the output order and metadata; words removed from the input are omitted from the corresponding enriched CSV.

Existing enrichment is read from `data/4_enriched_gemini/`, and each successful batch is saved atomically to a dated directory such as `data/4_enriched_gemini_20261112/`. Rerunning on the same date resumes missing words, including after a failed request. Use `--cache-dir` to select another source of existing enrichment and `--output-dir` to choose the output directory. A run with failed batches returns a nonzero exit code. Use `--dry-run` to inspect pending counts without API calls or writes, or pass a base word to process one family. `--overwrite` explicitly regenerates existing enrichment and is unnecessary for incremental updates.

This command does not generate exercises or publish files to `assets/enriched`.

Gemini requests use the standard structured-JSON generation endpoint with low thinking and a three-minute transport timeout. Transient failures are retried; a reported daily request quota stops queued requests until the quota resets or another model is selected. Use `--model <available-model>` to select a different model. Each successful batch remains reusable across subsequent runs.

For larger batches, increase `--request-timeout` (seconds) so long responses can finish. Valid rows from a partially invalid batch are checkpointed; subsequent runs request only its missing or invalid words. Temporary high-demand responses receive a longer retry delay.
