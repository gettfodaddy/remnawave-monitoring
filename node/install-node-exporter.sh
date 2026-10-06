#!/usr/bin/env bash
set -euo pipefail

# Debian/Ubuntu x86_64 installer. Verify the official release checksum before
# installing. For ARM64, use the official download page and change ARCH/hash.
VERSION="1.12.1"
ARCH="amd64"
SHA256="b51d8a76aa2a9156a55d501aca6276fae09e262259a5e4e831d2c2222f084e63"
FILE="node_exporter-${VERSION}.linux-${ARCH}.tar.gz"
URL="https://github.com/prometheus/node_exporter/releases/download/v${VERSION}/${FILE}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: sudo bash $0" >&2
  exit 1
fi

apt-get update
apt-get install -y curl tar ca-certificates
getent group node_exporter >/dev/null || groupadd --system node_exporter
id -u node_exporter >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin --gid node_exporter node_exporter
install -d -o root -g node_exporter -m 0750 /var/lib/node_exporter/textfile
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
curl -fL "$URL" -o "$tmpdir/$FILE"
echo "$SHA256  $tmpdir/$FILE" | sha256sum --check --status || { echo "SHA256 mismatch" >&2; exit 1; }
tar -xzf "$tmpdir/$FILE" -C "$tmpdir"
install -o root -g root -m 0755 "$tmpdir/node_exporter-${VERSION}.linux-${ARCH}/node_exporter" /usr/local/bin/node_exporter

install -o root -g root -m 0644 "$(dirname "$0")/node_exporter.service" /etc/systemd/system/node_exporter.service
systemctl daemon-reload
systemctl enable --now node_exporter
systemctl --no-pager --full status node_exporter
