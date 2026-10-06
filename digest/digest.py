#!/usr/bin/env python3
"""Daily Prometheus metrics summary to Telegram; no Remnawave API calls."""
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

PROM = os.environ.get("PROMETHEUS_URL", "http://prometheus:9090").rstrip("/")
TOKEN_FILE = os.environ.get("TELEGRAM_BOT_TOKEN_FILE", "/run/secrets/telegram_bot_token")
CHAT = os.environ["TELEGRAM_CHAT_ID"]
TZ = ZoneInfo(os.environ.get("TIMEZONE", "Europe/Moscow"))
HOUR = int(os.environ.get("REPORT_HOUR", "9"))
MINUTE = int(os.environ.get("REPORT_MINUTE", "0"))
STEP = "5m"
FILESYSTEM_EXCLUDE = 'fstype!~"tmpfs|overlay|squashfs|ramfs|devtmpfs"'


def prom_query(expression):
    url = PROM + "/api/v1/query?" + urllib.parse.urlencode({"query": expression})
    with urllib.request.urlopen(url, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))
    if data.get("status") != "success":
        raise RuntimeError("Prometheus query was unsuccessful")
    return data["data"]["result"]


def rows_by_node(expression):
    rows = prom_query(expression)
    return {r.get("metric", {}).get("node", "unknown"): float(r["value"][1]) for r in rows}


def rows_by_label(expression, label):
    rows = prom_query(expression)
    return {r.get("metric", {}).get(label, "unknown"): float(r["value"][1]) for r in rows}


def pretty_percent(value):
    return "—" if value is None else "%.1f%%" % value


def pretty_bytes(value):
    if value is None:
        return "—"
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    amount = value
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return "%.1f %s" % (amount, unit)
        amount /= 1024
    return "—"


def build_report():
    cpu_expr = 'max_over_time((100 * (1 - avg by (node) (rate(node_cpu_seconds_total{job="node",mode="idle"}[5m]))))[24h:5m])'
    mem_expr = 'max_over_time((100 * (1 - node_memory_MemAvailable_bytes{job="node"} / node_memory_MemTotal_bytes{job="node"}))[24h:5m])'
    disk_expr = 'min by (node) (min_over_time((100 * node_filesystem_avail_bytes{job="node",' + FILESYSTEM_EXCLUDE + '} / node_filesystem_size_bytes{job="node",' + FILESYSTEM_EXCLUDE + '})[24h:5m]))'
    uptime_expr = '100 * avg_over_time(probe_success{job="vpn_tcp"}[24h])'
    container_expr = 'remnawave_container_up{job="node"}'
    rx = 'sum by (node) (increase(node_network_receive_bytes_total{job="node",device!~"lo|docker.*|veth.*|br-.*"}[24h]))'
    tx = 'sum by (node) (increase(node_network_transmit_bytes_total{job="node",device!~"lo|docker.*|veth.*|br-.*"}[24h]))'
    rw_traffic = 'sum by (node_uuid) (increase(remnawave_node_inbound_upload_bytes{app="remnawave"}[24h])) + sum by (node_uuid) (increase(remnawave_node_inbound_download_bytes{app="remnawave"}[24h]))'
    rw_status = 'remnawave_node_status{app="remnawave"}'
    rw_names = 'remnawave_node_basic_info{app="remnawave"}'
    data = {
        "cpu": rows_by_node(cpu_expr), "memory": rows_by_node(mem_expr),
        "disk": rows_by_node(disk_expr), "uptime": rows_by_node(uptime_expr),
        "container": rows_by_node(container_expr), "rx": rows_by_node(rx),
        "tx": rows_by_node(tx),
        "rw_traffic": rows_by_label(rw_traffic, "node_uuid"),
        "rw_status": rows_by_label(rw_status, "node_uuid"),
    }
    names = {r.get("metric", {}).get("node_uuid", "unknown"): r.get("metric", {}).get("node_name", "unknown") for r in prom_query(rw_names)}
    nodes = sorted(set(data["cpu"]) | set(data["uptime"]) | set(data["container"]))
    today = datetime.now(TZ).strftime("%d.%m.%Y")
    lines = ["📊 <b>Сводка Remnawave за последние 24 часа</b>", "Дата: " + today, ""]
    if not nodes:
        lines.append("Метрики пока не поступили.")
    for node in nodes:
        available = data["uptime"].get(node)
        container = data["container"].get(node)
        state = "работает" if container == 1 else ("остановлен" if container == 0 else "нет метрики")
        traffic = data["rx"].get(node, 0) + data["tx"].get(node, 0)
        lines.extend([
            "<b>" + node + "</b>",
            "• VPN TCP доступность: " + pretty_percent(available),
            "• Пик CPU: " + pretty_percent(data["cpu"].get(node)),
            "• Пик RAM: " + pretty_percent(data["memory"].get(node)),
            "• Минимум свободного диска: " + pretty_percent(data["disk"].get(node)),
            "• Контейнер remnanode сейчас: " + state,
            "• Сетевой трафик хоста*: " + pretty_bytes(traffic),
            "",
        ])
    if data["rw_status"] or data["rw_traffic"]:
        lines.extend(["<b>Метрики из Remnawave Panel</b>"])
        for uuid in sorted(set(data["rw_status"]) | set(data["rw_traffic"])):
            status = "подключена" if data["rw_status"].get(uuid) == 1 else "отключена/нет метрики"
            name = names.get(uuid, uuid[:8])
            lines.append("• " + name + ": " + status + "; трафик inbound за 24 ч: " + pretty_bytes(data["rw_traffic"].get(uuid)))
        lines.append("")
    lines.append("* RX+TX по интерфейсам хоста за сутки; это не биллинг Remnawave.")
    lines.append("Трафик Remnawave рассчитан из inbound upload/download counters за окно хранения Prometheus.")
    return "\n".join(lines)


def send(text):
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        token = f.read().strip()
    data = urllib.parse.urlencode({"chat_id": CHAT, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request("https://api.telegram.org/bot" + token + "/sendMessage", data=data)
    with urllib.request.urlopen(req, timeout=20) as response:
        response.read()


def next_report_time(now):
    due = now.replace(hour=HOUR, minute=MINUTE, second=0, microsecond=0)
    if due <= now:
        due += timedelta(days=1)
    return due


if __name__ == "__main__":
    print("daily digest active; timezone=" + str(TZ) + " schedule=%02d:%02d" % (HOUR, MINUTE), flush=True)
    while True:
        now = datetime.now(TZ)
        due = next_report_time(now)
        time.sleep(max(1, int((due - now).total_seconds())))
        try:
            send(build_report())
            print("daily digest sent", flush=True)
        except Exception as exc:
            print("daily digest failed:", str(exc), flush=True)
