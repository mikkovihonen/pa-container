#!/bin/bash
set -e

# Inject the default route to the proxy FIRST — the isolated network has no
# gateway of its own, so without this the container can reach nothing (including
# the apt mirrors below, which egress through the proxy).
if [ -n "$DEFAULT_ROUTE" ]; then
    ip route replace default via $DEFAULT_ROUTE
fi

# ─── IPv6 policy (IPV6_ENABLED, injected by run.py) ───────────────────────
# Off (default): explicitly disable IPv6 so no tool silently tries an AAAA
# record and dead-ends (the proxy stack is IPv4-only), and force apt onto IPv4.
# On: add the IPv6 default route to the proxy (DEFAULT_ROUTE6) and leave apt
# free to use v6.
if [ "${IPV6_ENABLED}" = "true" ]; then
    if [ -n "$DEFAULT_ROUTE6" ]; then
        ip -6 route replace default via "$DEFAULT_ROUTE6" || echo "WARNING: could not set IPv6 default route"
    fi
    rm -f /etc/apt/apt.conf.d/99force-ipv4
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
    printf 'Acquire::ForceIPv4 "true";\n' > /etc/apt/apt.conf.d/99force-ipv4
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

# ─── Virtual Desktop environment & nested container forwarding ──────────────
if [ "${PA_CONTAINER_DESKTOP}" = "true" ]; then
    mkdir -p /run/user/1000 /tmp/.X11-unix
    chown agent:agent /run/user/1000
    chmod 700 /run/user/1000
    chmod 1777 /tmp/.X11-unix

    # Forward desktop resources into nested containers if containers.conf directory exists
    if [ -d /etc/containers/containers.conf.d ]; then
        _dri_mount=""
        if [ -e /dev/dri ]; then
            _dri_mount=', "type=bind,source=/dev/dri,destination=/dev/dri"'
        fi
        cat <<EOF > /etc/containers/containers.conf.d/60-pa-container-desktop.conf
[containers]
mounts = [
  "type=bind,source=/run/user/1000/wayland-0,destination=/run/user/1000/wayland-0",
  "type=bind,source=/tmp/.X11-unix,destination=/tmp/.X11-unix",
  "type=bind,source=/dev/shm,destination=/dev/shm"${_dri_mount}
]
env = [
  "DISPLAY=:0",
  "WAYLAND_DISPLAY=wayland-0",
  "XDG_RUNTIME_DIR=/run/user/1000"
]
EOF
    fi

    # Managed Chromium policy: disable DoH, trust system / local CAs
    mkdir -p /etc/chromium/policies/managed
    cat <<'EOF' > /etc/chromium/policies/managed/00-pa-container.json
{
  "DnsOverHttpsMode": "off",
  "BuiltInDnsClientEnabled": false,
  "PromptForDownloadLocation": false
}
EOF

    # Configure NSS DB system-wide if certutil is available
    if command -v certutil >/dev/null 2>&1; then
        mkdir -p /etc/pki/nssdb
        certutil -d "sql:/etc/pki/nssdb" -N --empty-password >/dev/null 2>&1 || true
        if [ -f /usr/local/share/ca-certificates/extra/mitmproxy-ca-cert.crt ]; then
            certutil -d "sql:/etc/pki/nssdb" -A -t "C,," -n "mitmproxy" -i /usr/local/share/ca-certificates/extra/mitmproxy-ca-cert.crt >/dev/null 2>&1 || true
        fi
    fi
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
    while IFS=$'\t' read -r key value; do
        if [[ -n "$key" ]]; then
            gosu agent git config --global "$key" "$value"
        fi
    done < <(echo "$HOST_GIT_CONFIG" | jq -r 'to_entries[] | [.key, .value] | @tsv')
fi


exec gosu agent bash -c '
    set -a; source /etc/environment; set +a;

    # ─── Virtual Desktop compositor & VNC/noVNC streaming ─────────────────────
    if [ "${PA_CONTAINER_DESKTOP}" = "true" ]; then
        if [ ! -e /dev/dri ]; then
            export GALLIUM_DRIVER=llvmpipe
            export LP_NUM_THREADS=$(nproc 2>/dev/null || echo 4)
            export MESA_GL_VERSION_OVERRIDE=4.5
            export MESA_GLSL_VERSION_OVERRIDE=450
            export LIBGL_ALWAYS_SOFTWARE=1
        fi

        # Initialize agent user NSS DB
        if command -v certutil >/dev/null 2>&1; then
            mkdir -p /home/agent/.pki/nssdb
            certutil -d "sql:/home/agent/.pki/nssdb" -N --empty-password >/dev/null 2>&1 || true
            if [ -f /etc/pa-container-ca.crt ]; then
                certutil -d "sql:/home/agent/.pki/nssdb" -A -t "C,," -n "mitmproxy" -i /etc/pa-container-ca.crt >/dev/null 2>&1 || true
            elif [ -f /usr/local/share/ca-certificates/extra/mitmproxy-ca-cert.crt ]; then
                certutil -d "sql:/home/agent/.pki/nssdb" -A -t "C,," -n "mitmproxy" -i /usr/local/share/ca-certificates/extra/mitmproxy-ca-cert.crt >/dev/null 2>&1 || true
            fi
        fi

        export WLR_BACKENDS=headless
        export WLR_LIBINPUT_NO_DEVICES=1
        export WAYLAND_DISPLAY=wayland-0
        export DISPLAY=:0
        export XDG_RUNTIME_DIR=/run/user/1000

        # Start labwc headless compositor in background
        labwc -s /bin/true >/dev/null 2>&1 &

        # Wait up to 5 seconds for wayland-0 socket to become available
        for _ in $(seq 1 50); do
            if [ -S "$XDG_RUNTIME_DIR/wayland-0" ]; then
                break
            fi
            sleep 0.1
        done

        # Configure headless output resolution
        _res="${PA_DESKTOP_RESOLUTION:-1920x1080}"
        if command -v wlr-randr >/dev/null 2>&1; then
            wlr-randr --output HEADLESS-1 --mode "${_res}@60Hz" 2>/dev/null || wlr-randr --output HEADLESS-1 --custom-mode "${_res}@60Hz" 2>/dev/null || true
        fi

        # Start wayvnc and websockify in background
        _wayvnc_gpu_arg=""
        if [ -e /dev/dri ]; then
            _wayvnc_gpu_arg="--gpu"
        fi
        wayvnc --render-cursor ${_wayvnc_gpu_arg} 127.0.0.1 5900 >/dev/null 2>&1 &

        websockify --web /usr/share/novnc 6080 127.0.0.1:5900 >/dev/null 2>&1 &

        # Provision virtual-desktop skill for active coding agents
        if [ -d /usr/local/share/pa-container/skills/virtual-desktop ]; then
            for _skill_dir in \
                /home/agent/.pi/agent/skills/virtual-desktop \
                /home/agent/.gemini/antigravity/skills/virtual-desktop \
                /home/agent/.config/opencode/skills/virtual-desktop
            do
                mkdir -p "$(dirname "$_skill_dir")"
                rm -rf "$_skill_dir"
                cp -a /usr/local/share/pa-container/skills/virtual-desktop "$_skill_dir"
            done
        fi
    else
        # Prune virtual-desktop skill when desktop is disabled
        rm -rf /home/agent/.pi/agent/skills/virtual-desktop \
               /home/agent/.gemini/antigravity/skills/virtual-desktop \
               /home/agent/.config/opencode/skills/virtual-desktop 2>/dev/null || true
    fi

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

    if [ "$PA_CONTAINER_MODE" = "t3" ]; then
        if ! command -v t3 >/dev/null 2>&1; then
            echo "ERROR: t3 CLI is not installed in the container." >&2
            echo "Install it via tools.include: [\"t3\"], npm install -g t3, or .pa-container/dependencies/root/commands.sh." >&2
            exit 1
        fi

        # Seed pre-installed T3 managed runtimes into /home/agent/.t3/tools if available
        if [ -d "/usr/local/share/t3/tools/antigravity-acp" ]; then
            mkdir -p /home/agent/.t3/tools
            cp -an /usr/local/share/t3/tools/antigravity-acp /home/agent/.t3/tools/ 2>/dev/null || true
        fi

        # Preflight login check for agent-native authenticated agents in T3 mode
        if [[ ",${PA_CONTAINER_ENABLED_AGENTS:-$PA_CONTAINER_AGENT}," == *",claude,"* ]] && [ -z "${ANTHROPIC_API_KEY}" ]; then
            if command -v claude >/dev/null 2>&1; then
                _auth_status=$(CLAUDE_CONFIG_DIR=/home/agent/.claude claude auth status --json 2>/dev/null || true)
                if ! echo "$_auth_status" | grep -q '"loggedIn"[[:space:]]*:[[:space:]]*true'; then
                    echo "=================================================================="
                    echo "  Claude Code requires authentication before starting T3."
                    echo "  Starting interactive login..."
                    echo "=================================================================="
                    CLAUDE_CONFIG_DIR=/home/agent/.claude claude auth login
                fi
            fi
        fi

        if [[ ",${PA_CONTAINER_ENABLED_AGENTS:-$PA_CONTAINER_AGENT}," == *",antigravity,"* ]] && [ -z "${GEMINI_API_KEY}" ]; then
            if command -v agy >/dev/null 2>&1; then
                if [ ! -f /home/agent/.gemini/antigravity/antigravity_state.pbtxt ]; then
                    echo "=================================================================="
                    echo "  Antigravity requires authentication before starting T3."
                    echo "  Starting interactive login..."
                    echo "=================================================================="
                    agy -p "Authentication check" || true
                fi
            fi
        fi

        echo "=================================================================="
        echo "  Starting T3 Code server for ${PA_CONTAINER_AGENT} inside pa-container..."
        echo "  Web UI: https://t3.codes"
        if [ -n "${T3_PUBLIC_URL}" ]; then
            echo "  Tunnel URL: ${T3_PUBLIC_URL}"
        fi
        echo "=================================================================="
        _shim="/usr/local/share/pa-container/t3-advertise-host.cjs"
        if [ -f "$_shim" ]; then
            export NODE_OPTIONS="${NODE_OPTIONS:+${NODE_OPTIONS} }--require ${_shim}"
        fi
        export T3_ADVERTISE_HOST="${T3_ADVERTISE_HOST}"
        extra_args=()
        if [ "${T3_LAN}" = "true" ]; then
            extra_args+=("--lan")
        fi

        exec t3 serve --base-dir /home/agent/.t3 --host 0.0.0.0 --port "${T3_PORT:-3773}" "${extra_args[@]}" "$@"
    else
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
                echo "ERROR: Unknown agent '${PA_CONTAINER_AGENT}'. Supported agents: pi, opencode, antigravity, claude" >&2
                exit 1
                ;;
        esac
    fi
' -- "$@"
