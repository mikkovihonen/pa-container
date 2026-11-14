#!/bin/bash
# Sourced inside agent session

if [ -n "$HOST_GIT_CONFIG" ]; then
    if command -v jq >/dev/null 2>&1; then
        while IFS=$'\t' read -r key value; do
            if [ -n "$key" ]; then
                git config --global "$key" "$value"
            fi
        done < <(echo "$HOST_GIT_CONFIG" | jq -r "to_entries[] | [.key, .value] | @tsv")
    else
        while IFS=$'\t' read -r key value; do
            if [ -n "$key" ]; then
                git config --global "$key" "$value"
            fi
        done < <(echo "$HOST_GIT_CONFIG" | sed -E "s/[{}]//g; s/\"([^\"]+)\": *\"([^\"]*)\"/\\1\t\\2/g" | tr "," "\n" | sed -E "s/^[[:space:]]+//")
    fi
fi

