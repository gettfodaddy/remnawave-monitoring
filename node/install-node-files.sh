#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: sudo bash $0" >&2
  exit 1
fi
BASE="$(cd "$(dirname "$0")" && pwd)"

install -d -o root -g node_exporter -m 0750 /var/lib/node_exporter/textfile
install -o root -g root -m 0755 "$BASE/collect-remnanode-state.sh" /usr/local/sbin/collect-remnanode-state
install -o root -g root -m 0644 "$BASE/remnanode-state-check.service" /etc/systemd/system/remnanode-state-check.service
install -o root -g root -m 0644 "$BASE/remnanode-state-check.timer" /etc/systemd/system/remnanode-state-check.timer
systemctl daemon-reload
systemctl enable --now remnanode-state-check.timer
systemctl start remnanode-state-check.service

if ! id monitorheal >/dev/null 2>&1; then
  useradd --create-home --shell /bin/sh monitorheal
else
  usermod --shell /bin/sh monitorheal
fi
passwd -l monitorheal >/dev/null 2>&1 || true
install -o root -g root -m 0755 "$BASE/monitor-heal-wrapper" /usr/local/sbin/monitor-heal-wrapper
install -o root -g root -m 0755 "$BASE/monitor-heal-action" /usr/local/sbin/monitor-heal-action
install -o root -g root -m 0440 "$BASE/monitor-heal.sudoers" /etc/sudoers.d/monitor-heal
visudo -cf /etc/sudoers.d/monitor-heal
install -d -o monitorheal -g monitorheal -m 0700 /home/monitorheal/.ssh
touch /home/monitorheal/.ssh/authorized_keys
chown monitorheal:monitorheal /home/monitorheal/.ssh/authorized_keys
chmod 0600 /home/monitorheal/.ssh/authorized_keys
echo
echo "Now append the restricted executor public key to /home/monitorheal/.ssh/authorized_keys"
echo 'restrict,command="/usr/local/sbin/monitor-heal-wrapper" ssh-ed25519 REPLACE_WITH_EXECUTOR_PUBLIC_KEY remnawave-healer'
echo "Then test metrics locally: curl -s http://127.0.0.1:9100/metrics | grep remnawave_container"
