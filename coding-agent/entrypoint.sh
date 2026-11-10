#!/bin/bash
set -e

# Inject the default route to the proxy FIRST — the isolated network has no
# gateway of its own, so without this the container can reach nothing (including
# package mirrors below, which egress through the proxy).
if [ -n "$DEFAULT_ROUTE" ]; then
    ip route replace default via $DEFAULT_ROUTE
fi

# ─── IPv6 policy (IPV6_ENABLED, injected by run.py) ───────────────────────
# Off (default): explicitly disable IPv6 so no tool silently tries an AAAA
# record and dead-ends (the proxy stack is IPv4-only), and force dnf onto IPv4.
# On: add the IPv6 default route to the proxy (DEFAULT_ROUTE6) and leave dnf
# free to use v6.
if [ "${IPV6_ENABLED}" = "true" ]; then
    if [ -n "$DEFAULT_ROUTE6" ]; then
        ip -6 route replace default via "$DEFAULT_ROUTE6" || echo "WARNING: could not set IPv6 default route"
    fi
    if [ -f /etc/dnf/dnf.conf ]; then
        sed -i '/^ip_resolve=/d' /etc/dnf/dnf.conf 2>/dev/null || true
    fi
else
    # Disable IPv6 so no tool silently tries an AAAA record and dead-ends (the
    # proxy stack is IPv4-only). podman already sets this at run time via
    # --sysctl — rootless namespaces mount /proc/sys/net read-only, so the write
    # below fails there (harmlessly);
    # Only warn if IPv6 is STILL enabled afterwards, so the redundant failed
    # write on podman isn't misreported as a problem.
    sysctl -w net.ipv6.conf.all.disable_ipv6=1 >/dev/null 2>&1 || true
    sysctl -w net.ipv6.conf.default.disable_ipv6=1 >/dev/null 2>&1 || true
    _v6_all=/proc/sys/net/ipv6/conf/all/disable_ipv6
    if [ -e "$_v6_all" ] && [ "$(cat "$_v6_all" 2>/dev/null)" != "1" ]; then
        echo "WARNING: could not disable IPv6 (all)"
    fi
    if [ -f /etc/dnf/dnf.conf ]; then
        if grep -q '^\[main\]' /etc/dnf/dnf.conf; then
            sed -i '/^ip_resolve=/d; /^\[main\]/a ip_resolve=4' /etc/dnf/dnf.conf 2>/dev/null || true
        else
            printf '[main]\nip_resolve=4\n' >> /etc/dnf/dnf.conf
        fi
    fi
fi

if ! getent group nobody >/dev/null 2>&1; then
    groupadd -r nobody 2>/dev/null || true
fi

# ─── Home directory ownership (/home/agent is mounted as tmpfs at runtime) ───
chown agent:agent /home/agent
chmod 755 /home/agent
for _user_dir in /home/agent/.local /home/agent/.local/share /home/agent/.config /home/agent/.cache; do
    if [ -d "$_user_dir" ]; then
        chown agent:agent "$_user_dir" 2>/dev/null || true
        chmod 755 "$_user_dir" 2>/dev/null || true
    fi
done

# ─── Shadow directories ownership (tmpfs / named volume mounts) ───────────
# Mount roots (tmpfs, named volumes) are created owned by root:root (0755).
# Chown them to agent:agent so non-root agent processes can write files and directories.
if [ -n "$CONTAINER_CHOWN_PATHS" ]; then
    IFS=':' read -ra _paths <<< "$CONTAINER_CHOWN_PATHS"
    for _path in "${_paths[@]}"; do
        if [ -d "$_path" ]; then
            chown agent:agent "$_path" 2>/dev/null || true
            chmod 755 "$_path" 2>/dev/null || true
        fi
    done
fi

# ─── Nested container support (PA_CONTAINER_NESTED, injected by run.py) ───
# Only the setup that genuinely needs root happens here, before `gosu agent`.
# Rootless podman needs a private XDG_RUNTIME_DIR for its locks and pid files,
# and it must own its own image store: the volume (or tmpfs) mounted at
# ~/.local/share/containers is freshly created and root-owned on the first run.
# The chown is deliberately non-recursive — a populated store already belongs to
# agent, and walking every layer would be slow for nothing.
if [ "${PA_CONTAINER_NESTED}" = "true" ]; then
    mkdir -p /run/user/1000
    chown agent:agent /run/user/1000
    chmod 700 /run/user/1000
    for _dir in /home/agent/.local /home/agent/.local/share /home/agent/.local/share/containers; do
        mkdir -p "$_dir" 2>/dev/null && chown agent:agent "$_dir" 2>/dev/null \
            || echo "WARNING: could not prepare nested image store at $_dir"
    done
fi

# ─── Execute Root Package Entrypoint Hooks ─────────────────────────────────
if [ -d /usr/local/share/pa-container/entrypoint.d/root ]; then
    for _hook in /usr/local/share/pa-container/entrypoint.d/root/*.sh; do
        [ -f "$_hook" ] || continue
        [ -x "$_hook" ] || chmod +x "$_hook"
        "$_hook"
    done
fi

# ─── Git workspace safety & protocol rewriting (config.yaml git.*) ───────────
if [ "${GIT_SAFE_DIRECTORY:-true}" = "true" ]; then
    git config --system --add safe.directory '*'
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

if [ -n "$HOST_GIT_CONFIG" ]; then
    if command -v jq >/dev/null 2>&1; then
        while IFS=$'\t' read -r key value; do
            if [[ -n "$key" ]]; then
                gosu agent git config --global "$key" "$value"
            fi
        done < <(echo "$HOST_GIT_CONFIG" | jq -r 'to_entries[] | [.key, .value] | @tsv')
    else
        while IFS=$'\t' read -r key value; do
            if [[ -n "$key" ]]; then
                gosu agent git config --global "$key" "$value"
            fi
        done < <(echo "$HOST_GIT_CONFIG" | sed -E 's/[{}]//g; s/"([^"]+)": *"([^"]*)"/\1\t\2/g' | tr ',' '\n' | sed -E 's/^[[:space:]]+//')
    fi
fi


exec gosu agent bash -c '
    set -a; source /etc/environment; set +a;

    # ─── Execute Agent Package Entrypoint Hooks ────────────────────────────────
    if [ -d /usr/local/share/pa-container/entrypoint.d/agent ]; then
        for _hook in /usr/local/share/pa-container/entrypoint.d/agent/*.sh; do
            [ -f "$_hook" ] || continue
            . "$_hook"
        done
    fi

    # ─── Dynamic Skill Projection Engine ───────────────────────────────────────
    # Automatically project installed skills from ACP packages into active agent directories
    for _pkg_skill in /usr/local/share/pa-container/packages/*/skill/SKILL.md; do
        [ -f "$_pkg_skill" ] || continue
        _dir_part="$(dirname "$_pkg_skill")"
        _skill_name="$(basename "$_dir_part")"
        if [ "$_skill_name" = "skill" ]; then
            _skill_name="$(basename "$(dirname "$_dir_part")")"
        fi
        for _agent_skills in \
            /home/agent/.pi/agent/skills \
            /home/agent/.gemini/antigravity/skills \
            /home/agent/.claude/skills \
            /home/agent/.config/opencode/skills; do
            mkdir -p "$_agent_skills/$_skill_name"
            cp -a "$_pkg_skill" "$_agent_skills/$_skill_name/SKILL.md" 2>/dev/null || true
        done
    done

    # ─── Source control credential helpers (SETUP_GIT_CREDENTIALS) ────────────
    if [ "${SETUP_GIT_CREDENTIALS}" = "true" ]; then
        if [ -n "${GH_TOKEN}" ]; then
            if command -v gh >/dev/null 2>&1; then
                gh auth setup-git >/dev/null 2>&1 || true
            fi
        fi
        if [ -n "${GITLAB_TOKEN}" ]; then
            if command -v glab >/dev/null 2>&1; then
                glab auth setup-git >/dev/null 2>&1 || true
            fi
        fi
    fi

    if [ -x .pa-container/dependencies/agent/commands.sh ]; then
        .pa-container/dependencies/agent/commands.sh
    fi

    # ─── Package Run Mode Execution (Orchestrators / Alternative Modes) ───────
    if [ -n "$PA_CONTAINER_MODE" ] && [ -x "/usr/local/share/pa-container/modes/${PA_CONTAINER_MODE}.sh" ]; then
        exec "/usr/local/share/pa-container/modes/${PA_CONTAINER_MODE}.sh" "$@"
    fi

    case "${PA_CONTAINER_AGENT}" in
        pi)
            exec pi "$@"
            ;;
        opencode)
            exec opencode "$@"
            ;;
        antigravity)
            exec agy "$@"
            ;;
        claude)
            exec claude "$@"
            ;;
        *)
            echo "ERROR: Unknown agent \"${PA_CONTAINER_AGENT}\". Supported agents: pi, opencode, antigravity, claude" >&2
            exit 1
            ;;
    esac
' -- "$@"
