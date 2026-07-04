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
- extracts `Unterbegriffe` or `Wortbildungen`
- looks up CEFR level from `data/2_interim/german_frequency_join.csv`
- looks up frequency from the same joined CSV
- writes a pipe-separated CSV for that word

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
done < data/1_input/word_bases_list.txt
```

That skips empty lines and category headings such as `Движение и перемещение:`.

## Outputs

After the pipeline completes, you should have:

- raw German API dumps in `data/1_input/GermanAPI/`
- a joined metadata table at `data/2_interim/german_frequency_join.csv`
- one CSV per base word in `data/3_output/`

You can also open [index.html](/Users/iyalchyk/@projects/DeutschSprint/index.html) in a browser to inspect the generated assets included in this repo.
