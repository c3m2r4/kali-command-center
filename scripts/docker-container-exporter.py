#!/usr/bin/python3
"""Expose a limited, read-only Docker inventory/stats view to Prometheus."""
import json
import re
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BIND = "172.22.0.1"  # kind Docker bridge gateway; not exposed on LAN/localhost
PORT = 19100
DOCKER = "/usr/bin/docker"


def run_docker(*args):
    return subprocess.run([DOCKER, *args], check=True, capture_output=True, text=True, timeout=20).stdout


def number(value):
    try:
        return float(value.rstrip("%"))
    except (ValueError, AttributeError):
        return 0.0


def bytes_value(value):
    match = re.match(r"^\s*([0-9]*\.?[0-9]+)\s*([kmgtpe]?i?b)?\s*$", value, re.I)
    if not match:
        return 0.0
    amount = float(match.group(1))
    unit = (match.group(2) or "B").lower()
    units = {"b": 1, "kb": 1000, "kib": 1024, "mb": 1000**2, "mib": 1024**2,
             "gb": 1000**3, "gib": 1024**3, "tb": 1000**4, "tib": 1024**4,
             "pb": 1000**5, "pib": 1024**5, "eb": 1000**6, "eib": 1024**6}
    return amount * units.get(unit, 1)


def pair_bytes(value):
    parts = [p.strip() for p in value.split("/")]
    return (bytes_value(parts[0]), bytes_value(parts[1])) if len(parts) == 2 else (0.0, 0.0)


def escape(value):
    return str(value or "").replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def sample(metric, labels, value):
    label_text = ",".join(f'{key}="{escape(val)}"' for key, val in labels.items())
    return f"{metric}{{{label_text}}} {value}"


def collect():
    inventory = [json.loads(line) for line in run_docker("ps", "-a", "--no-trunc", "--format", "{{json .}}").splitlines() if line.strip()]
    stats = [json.loads(line) for line in run_docker("stats", "--no-stream", "--format", "{{json .}}").splitlines() if line.strip()]
    stats_by_id = {row.get("ID", ""): row for row in stats}
    lines = [
        "# HELP docker_container_info Docker container inventory. Value is always 1.",
        "# TYPE docker_container_info gauge",
        "# HELP docker_container_running Whether the Docker container is running (1) or stopped (0).",
        "# TYPE docker_container_running gauge",
        "# HELP docker_container_cpu_percent CPU usage percentage from docker stats.",
        "# TYPE docker_container_cpu_percent gauge",
        "# HELP docker_container_memory_usage_bytes Current memory usage in bytes.",
        "# TYPE docker_container_memory_usage_bytes gauge",
        "# HELP docker_container_memory_limit_bytes Memory limit reported by Docker in bytes.",
        "# TYPE docker_container_memory_limit_bytes gauge",
        "# HELP docker_container_memory_percent Memory usage percentage from docker stats.",
        "# TYPE docker_container_memory_percent gauge",
        "# HELP docker_container_network_receive_bytes_total Network bytes received since container start, as reported by Docker.",
        "# TYPE docker_container_network_receive_bytes_total gauge",
        "# HELP docker_container_network_transmit_bytes_total Network bytes transmitted since container start, as reported by Docker.",
        "# TYPE docker_container_network_transmit_bytes_total gauge",
        "# HELP docker_container_block_read_bytes_total Block bytes read, as reported by Docker.",
        "# TYPE docker_container_block_read_bytes_total gauge",
        "# HELP docker_container_block_write_bytes_total Block bytes written, as reported by Docker.",
        "# TYPE docker_container_block_write_bytes_total gauge",
        "# HELP docker_container_processes Number of processes in the container.",
        "# TYPE docker_container_processes gauge",
    ]
    for item in inventory:
        container_id = item.get("ID", "")
        short_id = container_id[:12]
        name = item.get("Names", "")
        state = item.get("State", "unknown").lower()
        labels = {"container_id": container_id, "name": name, "image": item.get("Image", ""),
                  "state": state, "status": item.get("Status", ""), "ports": item.get("Ports", "")}
        lines.append(sample("docker_container_info", labels, 1))
        lines.append(sample("docker_container_running", {"name": name, "container_id": container_id}, int(state == "running")))
        stat = stats_by_id.get(short_id)
        if not stat:
            continue
        usage, limit = pair_bytes(stat.get("MemUsage", ""))
        net_rx, net_tx = pair_bytes(stat.get("NetIO", ""))
        block_read, block_write = pair_bytes(stat.get("BlockIO", ""))
        runtime_labels = {"name": name, "container_id": container_id}
        lines.append(sample("docker_container_cpu_percent", runtime_labels, number(stat.get("CPUPerc", "0"))))
        lines.append(sample("docker_container_memory_usage_bytes", runtime_labels, usage))
        lines.append(sample("docker_container_memory_limit_bytes", runtime_labels, limit))
        lines.append(sample("docker_container_memory_percent", runtime_labels, number(stat.get("MemPerc", "0"))))
        lines.append(sample("docker_container_network_receive_bytes_total", runtime_labels, net_rx))
        lines.append(sample("docker_container_network_transmit_bytes_total", runtime_labels, net_tx))
        lines.append(sample("docker_container_block_read_bytes_total", runtime_labels, block_read))
        lines.append(sample("docker_container_block_write_bytes_total", runtime_labels, block_write))
        lines.append(sample("docker_container_processes", runtime_labels, number(stat.get("PIDs", "0"))))
    return "\n".join(lines) + "\n"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            payload, status = b"ok\n", 200
        elif self.path == "/metrics":
            try:
                payload, status = collect().encode(), 200
            except Exception as exc:
                payload, status = (f"docker exporter collection failed: {exc}\n").encode(), 503
        else:
            payload, status = b"not found\n", 404
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


if __name__ == "__main__":
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()
