#!/usr/bin/env bash

set -euo pipefail

input_file="data/2_interim/word_bases_list.txt"
total=$(wc -l < "$input_file")
current=0
bar_width=30

while IFS= read -r line; do
    current=$((current + 1))
    python scripts/wiktionary_unterbegriffe.py "$line"

    if (( total > 0 )); then
        filled=$((current * bar_width / total))
        empty=$((bar_width - filled))
        percent=$((current * 100 / total))
        printf '\r[%s%s] %3d%% (%d/%d)' \
            "$(printf '%*s' "$filled" '' | tr ' ' '#')" \
            "$(printf '%*s' "$empty" '' | tr ' ' '.')" \
            "$percent" "$current" "$total"
    fi
done < "$input_file"

if (( total > 0 )); then
    printf '\n'
fi
