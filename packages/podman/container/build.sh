#!/bin/bash
# Build Podman 6, Netavark, and Aardvark-dns from source with established build tags
set -euo pipefail

PA_STAGE="${PA_STAGE:-/out}"
mkdir -p "${PA_STAGE}/usr/local/bin" "${PA_STAGE}/usr/local/libexec/podman" "${PA_STAGE}/etc/containers/containers.conf.d"

# ─── 1. Build Podman ─────────────────────────────────────────────────────────
echo "=== Building Podman ${PODMAN_VERSION} ==="
if ! command -v go >/dev/null 2>&1 || [ "$(go version | grep -oE 'go1\.[0-9]+' | sed 's/go1\.//')" -lt 26 ]; then
    echo "Staging Go 1.27.3 compiler for Podman build..."
    arch="$(uname -m)"
    case "$arch" in
        x86_64) go_arch="amd64"; go_sha="65efbc80fdc1fa2cd2631cad5b481777a68e8725f34e89f50fc6ac714e379b40" ;;
        aarch64) go_arch="arm64"; go_sha="a06e99309dbcbdca1a8ccd2282c3ee146e55930886e26b4f1193269587165f49" ;;
        *) go_arch="$arch"; go_sha="" ;;
    esac
    curl -fsSL -o /tmp/go.tar.gz "https://go.dev/dl/go1.27.3.linux-${go_arch}.tar.gz"
    if [ -n "$go_sha" ]; then
        echo "${go_sha}  /tmp/go.tar.gz" | sha256sum -c -
    fi
    tar -C /tmp -xzf /tmp/go.tar.gz
    export PATH="/tmp/go/bin:${PATH}"
    rm -f /tmp/go.tar.gz
fi
go version

git clone --depth 1 --branch "${PODMAN_VERSION}" https://github.com/containers/podman.git /tmp/podman
cd /tmp/podman
head_commit="$(git rev-parse HEAD)"
if [ -n "${PODMAN_COMMIT:-}" ] && [ "${head_commit}" != "${PODMAN_COMMIT}" ]; then
    echo "WARNING: Podman commit ${head_commit} does not match expected ${PODMAN_COMMIT}"
fi

export GOFLAGS="-mod=vendor"
export GOTOOLCHAIN="local"
make BUILDTAGS="${BUILDTAGS}" bin/podman bin/rootlessport

install -D -m 0755 bin/podman "${PA_STAGE}/usr/local/bin/podman"
install -D -m 0755 bin/rootlessport "${PA_STAGE}/usr/local/libexec/podman/rootlessport"

# Docker CLI wrapper pointing to Podman
cat << 'EOF' > "${PA_STAGE}/usr/local/bin/docker"
#!/bin/sh
exec /usr/local/bin/podman "$@"
EOF
chmod 0755 "${PA_STAGE}/usr/local/bin/docker"

# ─── 2. Build Netavark & Aardvark-dns ─────────────────────────────────────────
echo "=== Building Netavark ${NETAVARK_VERSION} ==="
git clone --depth 1 --branch "${NETAVARK_VERSION}" https://github.com/containers/netavark.git /tmp/netavark
cd /tmp/netavark
curl -fsSL -o /tmp/netavark-vendor.tar.gz "https://github.com/containers/netavark/releases/download/${NETAVARK_VERSION}/netavark-${NETAVARK_VERSION}-vendor.tar.gz"
echo "${NETAVARK_VENDOR_SHA256}  /tmp/netavark-vendor.tar.gz" | sha256sum -c -
tar -xzf /tmp/netavark-vendor.tar.gz -C /tmp/netavark
mkdir -p /tmp/netavark/.cargo
cat << 'EOF' > /tmp/netavark/.cargo/config.toml
[source.crates-io]
replace-with = "vendored-sources"

[source.vendored-sources]
directory = "vendor"
EOF
cargo build --release --offline --bin netavark
install -D -m 0755 target/release/netavark "${PA_STAGE}/usr/local/libexec/podman/netavark"

echo "=== Building Aardvark-dns ${AARDVARK_VERSION} ==="
git clone --depth 1 --branch "${AARDVARK_VERSION}" https://github.com/containers/aardvark-dns.git /tmp/aardvark-dns
cd /tmp/aardvark-dns
curl -fsSL -o /tmp/aardvark-vendor.tar.gz "https://github.com/containers/aardvark-dns/releases/download/${AARDVARK_VERSION}/aardvark-dns-${AARDVARK_VERSION}-vendor.tar.gz"
echo "${AARDVARK_VENDOR_SHA256}  /tmp/aardvark-vendor.tar.gz" | sha256sum -c -
tar -xzf /tmp/aardvark-vendor.tar.gz -C /tmp/aardvark-dns
mkdir -p /tmp/aardvark-dns/.cargo
cat << 'EOF' > /tmp/aardvark-dns/.cargo/config.toml
[source.crates-io]
replace-with = "vendored-sources"

[source.vendored-sources]
directory = "vendor"
EOF
cargo build --release --offline --bin aardvark-dns
install -D -m 0755 target/release/aardvark-dns "${PA_STAGE}/usr/local/libexec/podman/aardvark-dns"

# ─── 3. Containers Configuration Files ───────────────────────────────────────
cat << 'EOF' > "${PA_STAGE}/etc/containers/policy.json"
{
  "default": [{"type": "insecureAcceptAnything"}],
  "transports": {
    "docker-daemon": {"": [{"type": "insecureAcceptAnything"}]}
  }
}
EOF

cat << 'EOF' > "${PA_STAGE}/etc/containers/registries.conf"
unqualified-search-registries = ["docker.io"]
short-name-mode = "enforcing"
EOF

cat << 'EOF' > "${PA_STAGE}/etc/containers/containers.conf.d/50-pa-container.conf"
[containers]
mounts = [
  "type=bind,source=/etc/pki/tls/certs/ca-bundle.crt,destination=/etc/pa-container-ca.crt,ro=true",
]
env = [
  "SSL_CERT_FILE=/etc/pa-container-ca.crt",
  "NODE_EXTRA_CA_CERTS=/etc/pa-container-ca.crt",
  "REQUESTS_CA_BUNDLE=/etc/pa-container-ca.crt",
  "CURL_CA_BUNDLE=/etc/pa-container-ca.crt",
  "GIT_SSL_CAINFO=/etc/pa-container-ca.crt",
]
log_driver = "k8s-file"
netns = "bridge"

[engine]
cgroup_manager = "cgroupfs"
compose_providers = ["podman-compose"]
compose_warning_logs = false
EOF

# ─── 4. Install podman-compose ───────────────────────────────────────────────
echo "=== Installing podman-compose ${PODMAN_COMPOSE_VERSION} ==="
/usr/local/bin/python3 -m pip install --root-user-action=ignore --root "${PA_STAGE}" --ignore-installed "podman-compose==${PODMAN_COMPOSE_VERSION}"

# ─── 5. Stage virtualization stack & subordinate IDs ────────────────────────
mkdir -p "${PA_STAGE}/usr/bin" "${PA_STAGE}/usr/sbin" "${PA_STAGE}/etc"
for bin in crun conmon catatonit fuse-overlayfs pasta newuidmap newgidmap; do
    p="$(command -v "$bin" || true)"
    if [ -n "$p" ]; then
        cp -a "$p" "${PA_STAGE}/usr/bin/"
    fi
done
for sbin in nft iptables-nft; do
    p="$(command -v "$sbin" || true)"
    if [ -n "$p" ]; then
        cp -a "$p" "${PA_STAGE}/usr/sbin/"
    fi
done

printf 'agent:1:999\nagent:1001:64535\n' > "${PA_STAGE}/etc/subuid"
cp "${PA_STAGE}/etc/subuid" "${PA_STAGE}/etc/subgid"

# Verification
"${PA_STAGE}/usr/local/bin/podman" --version
[ -x "${PA_STAGE}/usr/local/bin/docker" ]
[ -x "${PA_STAGE}/usr/local/bin/podman-compose" ]
PATH="${PA_STAGE}/usr/local/bin:${PATH}" PYTHONPATH="${PA_STAGE}/usr/local/lib/python3.15/site-packages" "${PA_STAGE}/usr/local/bin/podman-compose" --version

rm -rf /tmp/podman /tmp/netavark /tmp/aardvark-dns /tmp/*.tar.gz
echo "=== Podman build complete ==="
