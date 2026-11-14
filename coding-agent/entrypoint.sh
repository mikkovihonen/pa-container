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



exec gosu agent bash -c '
    set -a; source /etc/environment; set +a;

    # ─── Execute Agent Package Entrypoint Hooks ────────────────────────────────
    if [ -d /usr/local/share/pa-container/entrypoint.d/agent ]; then
        for _hook in /usr/local/share/pa-container/entrypoint.d/agent/*.sh; do
            [ -f "$_hook" ] || continue
            . "$_hook"
        done
    fi

    # Ensure sourced hooks do not leave nounset active
    set +u 2>/dev/null || true

    # ─── Dynamic Skill Projection Engine ───────────────────────────────────────
    set +u 2>/dev/null || true
    _share_packages_dir="${PA_SHARE_PACKAGES_DIR:-/usr/local/share/pa-container/packages}"
    _share_agents_dir="${PA_SHARE_AGENTS_DIR:-/usr/local/share/pa-container/agents}"

    _target_agent_skills_dirs=()
    if [ -n "${PA_AGENT_SKILLS_DIRS:-}" ]; then
        IFS=":" read -ra _target_agent_skills_dirs <<< "$PA_AGENT_SKILLS_DIRS"
    else
        for _path_file in "$_share_agents_dir"/*/skills_path; do
            [ -f "$_path_file" ] || continue
            _p="$(cat "$_path_file")"
            case "$_p" in
                /*) _target_agent_skills_dirs+=("$_p") ;;
                *)  _target_agent_skills_dirs+=("${PA_HOME_AGENT_DIR:-/home/agent}/$_p") ;;
            esac
        done
    fi

    # Legacy core packages unbundled from baseline (reconciled without .pa-projected marker)
    _legacy_acp_packages=" code-intelligence data-tools podman "
    _known_acp_packages="${_legacy_acp_packages}"
    if [ -f "$_share_packages_dir/../acp-packages.txt" ]; then
        _known_acp_packages="$(cat "$_share_packages_dir/../acp-packages.txt" 2>/dev/null) ${_legacy_acp_packages}"
    fi

    # 1. Prune stale projected skills no longer present in this container image
    for _agent_skills in "${_target_agent_skills_dirs[@]+"${_target_agent_skills_dirs[@]}"}"; do
        [ -d "$_agent_skills" ] || continue
        for _existing_skill_dir in "$_agent_skills"/*; do
            [ -d "$_existing_skill_dir" ] || continue
            _existing_skill_name="$(basename "$_existing_skill_dir")"

            _is_managed=false
            if [ -f "$_existing_skill_dir/.pa-projected" ]; then
                _is_managed=true
            else
                case "$_known_acp_packages" in
                    *" $_existing_skill_name "*) _is_managed=true ;;
                esac
            fi

            if [ "$_is_managed" = "true" ]; then
                if [ ! -f "$_share_packages_dir/$_existing_skill_name/skill/SKILL.md" ] && \
                   [ ! -f "$_share_packages_dir"/*/"$_existing_skill_name/skill/SKILL.md" ] && \
                   [ ! -f "$_share_packages_dir/$_existing_skill_name/base/skill/SKILL.md" ]; then
                    rm -rf "$_existing_skill_dir"
                fi
            fi
        done
    done

    # 2. Automatically project installed skills from ACP packages into active agent directories
    for _pkg_skill in "$_share_packages_dir"/*/skill/SKILL.md "$_share_packages_dir"/*/*/skill/SKILL.md; do
        [ -f "$_pkg_skill" ] || continue

        _skill_name=""
        if grep -q "^name: " "$_pkg_skill" 2>/dev/null; then
            _skill_name="$(grep -m 1 "^name:" "$_pkg_skill" | sed "s/^name:[[:space:]]*//" | tr -d " \"\r\t" | tr -d "\047")"
        fi

        if [ -z "$_skill_name" ]; then
            _dir_part="$(dirname "$_pkg_skill")"
            _parent_dir="$(dirname "$_dir_part")"
            _pkg_leaf="$(basename "$_parent_dir")"
            if [ "$_pkg_leaf" = "base" ]; then
                _skill_name="$(basename "$(dirname "$_parent_dir")")"
            else
                _skill_name="$_pkg_leaf"
            fi
        fi

        for _agent_skills in "${_target_agent_skills_dirs[@]+"${_target_agent_skills_dirs[@]}"}"; do
            mkdir -p "$_agent_skills/$_skill_name"
            cp -a "$_pkg_skill" "$_agent_skills/$_skill_name/SKILL.md" 2>/dev/null || true
            touch "$_agent_skills/$_skill_name/.pa-projected" 2>/dev/null || true
        done
    done


    if [ -x .pa-container/dependencies/agent/commands.sh ]; then
        .pa-container/dependencies/agent/commands.sh
    fi

    # ─── Package Run Mode Execution (Orchestrators / Alternative Modes) ───────
    if [ -n "${PA_CONTAINER_MODE:-}" ] && [ -x "/usr/local/share/pa-container/modes/${PA_CONTAINER_MODE}.sh" ]; then
        exec "/usr/local/share/pa-container/modes/${PA_CONTAINER_MODE}.sh" "$@"
    fi

    if [ "$#" -eq 0 ]; then
        if [ -n "${PA_CONTAINER_AGENT:-}" ]; then
            set -- "$PA_CONTAINER_AGENT"
        elif [ -s /usr/local/share/pa-container/default_agent ]; then
            set -- "$(cat /usr/local/share/pa-container/default_agent)"
        else
            set -- bash
        fi
    fi

    exec "$@"
' -- "$@"
