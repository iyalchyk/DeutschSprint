#!/usr/bin/env python3
"""Export locally attested verbs absent from the existing family files."""

import argparse
import csv
import re
from pathlib import Path

from build_frequency_csv import load_german_api_records
from wiktionary_unterbegriffe import (
    build_rows, load_frequency_map, load_level_map, normal_key, write_rows,
)

DEREKO = Path('data/1_input/DeReKo-2014-II-MainArchive-STT.100000.freq/DeReKo-2014-II-MainArchive-STT.100000.freq')
API = Path('data/1_input/GermanAPI/german_api_all_levels.json')
JOINED = Path('data/2_interim/german_frequency_join.csv')
FAMILIES = Path('data/3_output')
VERB = re.compile(r'[a-zäöüß]+(?:en|n)\Z')
# Common separable and inseparable verb prefixes. Only count a match when
# both the complete verb and its remaining base are attested candidates.
PREFIXES = frozenset('ab an auf aus bei be dar durch ein emp ent er fehl fern fest fort frei gegen her heraus herein herunter hervor hin hinaus hinein hinter hoch los mit nach nieder über um unter ver vor weg weiter wider wieder zu zurück zusammen'.split())


def related_words(words):
    """Find attested prefix/base pairs, including bases of known variants."""
    related = set()
    for word in words:
        remaining = {word}
        seen = set()
        while remaining:
            part = remaining.pop()
            if part in seen:
                continue
            seen.add(part)
            for prefix in PREFIXES:
                if part.startswith(prefix):
                    base = part[len(prefix):]
                    if base in words:
                        related.update((word, base))
                    if base:
                        remaining.add(base)
    return related



def candidates(dereko, api):
    words = set()
    with dereko.open(encoding='utf-8') as source:
        for line in source:
            columns = line.rstrip('\n').split('\t')
            if len(columns) != 4:
                raise ValueError(f'Invalid DeReKo row: {line!r}')
            _, lemma, pos, _ = columns
            if pos.startswith(('VV', 'VA', 'VM')) and VERB.fullmatch(lemma):
                words.add(lemma)
    for record in load_german_api_records(api):
        word = record['german']
        if str(record.get('pos', '')).strip().casefold() == 'verb' and VERB.fullmatch(word):
            words.add(word)
    return words


def family_words(directory, output):
    words = set()
    for path in sorted(directory.glob('*.csv')):
        if path.resolve() == output.resolve() or path.name.startswith('_'):
            continue
        with path.open(encoding='utf-8', newline='') as source:
            reader = csv.DictReader(source, delimiter='|')
            if not reader.fieldnames or not {'word_base', 'word'} <= set(reader.fieldnames):
                raise ValueError(f'Invalid family CSV: {path}')
            for row in reader:
                words.update(normal_key(row[field]) for field in ('word_base', 'word') if row[field])
    return words


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dereko', type=Path, default=DEREKO)
    parser.add_argument('--api', type=Path, default=API)
    parser.add_argument('--joined', type=Path, default=JOINED)
    parser.add_argument('--families', type=Path, default=FAMILIES)
    parser.add_argument('--output', type=Path, default=FAMILIES / '_single_verbs.csv')
    args = parser.parse_args()
    if not args.families.is_dir():
        parser.error(f'Family directory does not exist: {args.families}')
    levels = load_level_map(str(args.joined), 0)
    frequencies, ranks = load_frequency_map(str(args.joined), 0)
    covered = family_words(args.families, args.output)
    all_words = candidates(args.dereko, args.api)
    related = related_words(all_words | covered)
    words = sorted((word for word in all_words if normal_key(word) not in covered and word not in related), key=normal_key)
    rows = [row for word in words for row in build_rows(word, [], levels, frequencies, ranks, True)]
    write_rows(rows, args.output)
    print(f'Wrote {len(rows)} verbs to {args.output}; {len(words) - len(rows)} lacked DWDS frequency')


if __name__ == '__main__':
    main()
