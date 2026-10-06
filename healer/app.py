#!/usr/bin/env python3
"""Minimal, allowlisted Alertmanager webhook executor for Remnawave nodes."""
import hmac
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROM = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090").rstrip("/")
NODES_FILE = os.environ.get("NODES_FILE", "/etc/healer/nodes.json")
SSH_KEY = os.environ.get("SSH_KEY", "/run/secrets/healer_ssh_key")
KNOWN_HOSTS = os.environ.get("SSH_KNOWN_HOSTS", "/etc/healer/known_hosts")
DB = os.environ.get("STATE_DB", "/var/lib/healer/state.sqlite3")
TOKEN_FILE = os.environ.get("BEARER_TOKEN_FILE", "/run/secrets/healer_bearer_token")
TG_TOKEN_FILE = os.environ.get("TELEGRAM_BOT_TOKEN_FILE", "/run/secrets/telegram_bot_token")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
COOLDOWN = int(os.environ.get("COOLDOWN_SECONDS", "900"))
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"
ALERT_NAME = "VPNNodeNeedsHeal"
NODE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
LOCK = threading.Lock()


def read_secret(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def connect_db():
    conn = sqlite3.connect(DB, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS incidents (fingerprint TEXT PRIMARY KEY, node TEXT NOT NULL, state TEXT NOT NULL, action_at INTEGER, result TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS nodes (node TEXT PRIMARY KEY, last_action INTEGER NOT NULL)")
    conn.commit()
    return conn


def query(promql):
    url = PROM + "/api/v1/query?" + urllib.parse.urlencode({"query": promql})
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("status") != "success":
        raise RuntimeError("Prometheus query failed")
    return payload.get("data", {}).get("result", [])


def query_has_value(promql, expected):
    result = query(promql)
    return any(float(row.get("value", [0, "0"])[1]) == expected for row in result)


def confirm_incident(node):
    # Every probe sample in the last 3 minutes must have failed.
    selector = '{job="vpn_tcp",node="' + node + '"}'
    if not query_has_value("max_over_time(probe_success" + selector + "[3m])", 0):
        return False, "external VPN port is not continuously failing"
    if not query_has_value('up{job="node",node="' + node + '"}', 1):
        return False, "node_exporter is not healthy"
    if not query_has_value('remnawave_container_up{node="' + node + '"}', 1):
        return False, "remnanode container is not running"
    if not query_has_value('time() - remnawave_container_check_timestamp_seconds{node="' + node + '"} < bool 90', 1):
        return False, "container state check is stale"
    return True, "all independent checks confirm a running but unreachable node"


def send_telegram(message):
    if not TG_CHAT:
        return
    try:
        token = read_secret(TG_TOKEN_FILE)
        body = urllib.parse.urlencode({"chat_id": TG_CHAT, "text": message, "disable_web_page_preview": "true"}).encode()
        req = urllib.request.Request("https://api.telegram.org/bot" + token + "/sendMessage", data=body)
        with urllib.request.urlopen(req, timeout=8) as response:
            response.read()
    except Exception as exc:
        print("telegram notification failed:", str(exc), flush=True)


def perform_heal(node, fingerprint):
    if not NODE_RE.fullmatch(node):
        return "rejected invalid node label"
    with open(NODES_FILE, "r", encoding="utf-8") as f:
        nodes = json.load(f)
    if node not in nodes:
        return "rejected: node is not in allowlist"
    host = nodes[node].get("ssh_host", "")
    if not re.fullmatch(r"[A-Za-z0-9.:-]+", host):
        return "rejected: invalid SSH host in allowlist"

    ok, reason = confirm_incident(node)
    if not ok:
        return "no action: " + reason

    now = int(time.time())
    conn = connect_db()
    try:
        previous = conn.execute("SELECT state, action_at FROM incidents WHERE fingerprint=?", (fingerprint,)).fetchone()
        if previous and previous[0] == "acted":
            return "no action: this alert fingerprint was already handled"
        last = conn.execute("SELECT last_action FROM nodes WHERE node=?", (node,)).fetchone()
        if last and now - last[0] < COOLDOWN:
            return "no action: node cooldown active"
        # Reserve the incident before invoking SSH so webhook retries cannot
        # run overlapping restarts. A new firing after a resolved event gets
        # a new Alertmanager fingerprint lifecycle and must pass cooldown.
        conn.execute("INSERT OR REPLACE INTO incidents VALUES (?, ?, 'acted', ?, ?)", (fingerprint, node, now, "reserved"))
        conn.execute("INSERT OR REPLACE INTO nodes VALUES (?, ?)", (node, now))
        conn.commit()
    finally:
        conn.close()

    if DRY_RUN:
        result = "DRY RUN: would restart only remnanode on " + node
    else:
        command = [
            "ssh", "-i", SSH_KEY,
            "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes",
            "-o", "StrictHostKeyChecking=yes",
            "-o", "UserKnownHostsFile=" + KNOWN_HOSTS,
            "-o", "ConnectTimeout=10",
            "monitorheal@" + host,
            "restart-remnanode",
        ]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
            result = "restart command succeeded" if completed.returncode == 0 else "restart command failed (exit " + str(completed.returncode) + ")"
        except Exception as exc:
            result = "restart command error: " + str(exc)[:250]

    conn = connect_db()
    try:
        conn.execute("UPDATE incidents SET result=? WHERE fingerprint=?", (result, fingerprint))
        conn.commit()
    finally:
        conn.close()
    send_telegram("🛠 Автохил " + node + ": " + result)
    print("node=" + node + " fingerprint=" + fingerprint + " result=" + result, flush=True)
    return result


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("http:", fmt % args, flush=True)

    def do_POST(self):
        if self.path != "/alertmanager":
            self.send_error(404)
            return
        expected = "Bearer " + read_secret(TOKEN_FILE)
        supplied = self.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied, expected):
            self.send_error(401)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 1_000_000:
                self.send_error(413)
                return
            payload = json.loads(self.rfile.read(length))
            outcomes = []
            with LOCK:
                for alert in payload.get("alerts", []):
                    labels = alert.get("labels", {})
                    if labels.get("alertname") != ALERT_NAME:
                        continue
                    node = labels.get("node", "")
                    fingerprint = alert.get("fingerprint", "")
                    if not fingerprint:
                        continue
                    if alert.get("status") == "resolved":
                        conn = connect_db()
                        try:
                            conn.execute("UPDATE incidents SET state='resolved' WHERE fingerprint=?", (fingerprint,))
                            conn.commit()
                        finally:
                            conn.close()
                        outcomes.append("resolved " + node)
                    elif alert.get("status") == "firing" and labels.get("autoheal") == "true":
                        outcomes.append(node + ": " + perform_heal(node, fingerprint))
            body = json.dumps({"status": "ok", "results": outcomes}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            print("webhook processing error:", str(exc), flush=True)
            self.send_error(500, "processing error")


if __name__ == "__main__":
    connect_db().close()
    print("healer listening on :8080; dry_run=" + str(DRY_RUN), flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
