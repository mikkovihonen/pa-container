#!/bin/bash
set -euo pipefail

# ─── Git workspace safety & protocol rewriting (config.yaml git.*) ───────────
if [ "${GIT_SAFE_DIRECTORY:-true}" = "true" ]; then
    git config --system --add safe.directory "*"
fi

if [ "${GIT_REWRITE_SSH:-true}" = "true" ]; then
    git config --system --add url."https://github.com/".insteadOf "git@github.com:"
    git config --system --add url."https://github.com/".insteadOf "ssh://git@github.com/"
    git config --system --add url."https://gitlab.com/".insteadOf "git@gitlab.com:"
    git config --system --add url."https://gitlab.com/".insteadOf "ssh://git@gitlab.com/"
    git config --system --add url."https://codeberg.org/".insteadOf "git@codeberg.org:"
    git config --system --add url."https://codeberg.org/".insteadOf "ssh://git@codeberg.org/"
    git config --system --add url."https://bitbucket.org/".insteadOf "git@bitbucket.org:"
    git config --system --add url."https://bitbucket.org/".insteadOf "ssh://git@bitbucket.org/"
    git config --system --add url."https://git.cafe/".insteadOf "git@git.cafe:"
    git config --system --add url."https://git.cafe/".insteadOf "ssh://git@git.cafe/"
fi
