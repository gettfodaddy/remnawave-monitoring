#!/usr/bin/env bash
set -euo pipefail

OUT="/var/lib/node_exporter/textfile/remnawave_container.prom"
TMP="${OUT}.tmp"
NOW="$(date +%s)"
RUNNING=0

if /usr/bin/docker inspect --format '{{.State.Running}}' remnanode 2>/dev/null | /usr/bin/grep -qx true; then
  RUNNING=1
fi

{
  echo '# HELP remnawave_container_up Whether the Remnawave Node container is running.'
  echo '# TYPE remnawave_container_up gauge'
  echo "remnawave_container_up $RUNNING"
  echo '# HELP remnawave_container_check_timestamp_seconds Unix time of the last container state check.'
  echo '# TYPE remnawave_container_check_timestamp_seconds gauge'
  echo "remnawave_container_check_timestamp_seconds $NOW"
} > "$TMP"
/usr/bin/chown root:node_exporter "$TMP"
/usr/bin/chmod 0640 "$TMP"
/usr/bin/mv -f "$TMP" "$OUT"
