#!/bin/bash
# Shared helpers for ACP package build scripts.
# Sourced automatically via BASH_ENV in the package builder stage.
set -euo pipefail

PA_STAGE="${PA_STAGE:-/out}"

standard_arch() {
    case "$(uname -m)" in
        x86_64) echo "amd64" ;;
        aarch64|arm64) echo "arm64" ;;
        *) uname -m ;;
    esac
}

require_env() {
    local missing=0
    for name in "$@"; do
        if [ -z "${!name:-}" ]; then
            echo "ERROR: $(basename "$0") requires ${name}, which is unset or empty." >&2
            missing=1
        fi
    done
    if [ "${missing}" -ne 0 ]; then
        return 1
    fi
}

fetch_verified() {
    local url="$1" sha="$2" dest="$3"
    echo "Downloading ${url##*/}"
    mkdir -p "$(dirname "${dest}")"
    curl -fsSL --retry 5 --retry-delay 3 --retry-all-errors -o "${dest}" "${url}"
    echo "${sha}  ${dest}" | sha256sum -c - > /dev/null
}

clone_verified() {
    local repo="$1" tag="$2" commit="$3" dir="$4"
    echo "Cloning ${repo##*/} ${tag}"
    mkdir -p "$(dirname "${dir}")"
    git -c advice.detachedHead=false clone --quiet --depth 1 --branch "${tag}" "${repo}" "${dir}"

    local head
    head="$(git -C "${dir}" rev-parse HEAD)"
    if [ "${head}" != "${commit}" ]; then
        echo "ERROR: ${repo} ${tag} resolves to ${head}, expected ${commit}." >&2
        return 1
    fi
}

run_logged() {
    local desc="$1"
    local log="$2"
    shift 2

    echo "${desc}"
    mkdir -p "$(dirname "${log}")"
    if ! "$@" > "${log}" 2>&1; then
        echo "ERROR: ${desc} failed. Last 60 lines of ${log}:" >&2
        tail -n 60 "${log}" >&2
        return 1
    fi
}

stage_record() {
    local fragment_dir="${PA_STAGE}/usr/local/share/pa-container/toolchain-versions.d"
    local name
    name="$(basename "$0" .sh)"
    if [ "${name}" = "build" ]; then
        name="$(basename "$(dirname "$0")")"
    fi
    local fragment="${fragment_dir}/${name}.txt"

    mkdir -p "${fragment_dir}"
    printf '%-14s %s\n' "$1" "$2" >> "${fragment}"
}

mem_avail_mib() {
    awk '/^MemAvailable:/ {print int($2 / 1024)}' /proc/meminfo
}

mem_capped_jobs() {
    local mib_per_job="$1"
    local cpu_jobs mem_jobs

    cpu_jobs="$(nproc)"
    mem_jobs=$(($(mem_avail_mib) / mib_per_job))
    if [ "${mem_jobs}" -lt 1 ]; then
        mem_jobs=1
    fi
    if [ "${mem_jobs}" -lt "${cpu_jobs}" ]; then
        echo "${mem_jobs}"
    else
        echo "${cpu_jobs}"
    fi
}
