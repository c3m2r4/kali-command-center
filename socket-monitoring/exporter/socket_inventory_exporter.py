#!/usr/bin/env python3
"""Read-only exporter for the host's TCP listening and UDP socket inventory."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn, UnixStreamServer
from typing import Callable

SS_BIN = "/usr/bin/ss"
SUDO_BIN = "/usr/bin/sudo"
PROCESS_RE = re.compile(r'\("((?:[^"\\]|\\.)*)",pid=(\d+),fd=\d+\)')


def split_endpoint(value: str) -> tuple[str, str]:
    """Split ss numeric endpoint into address and port, including IPv6."""
    value = value.strip()
    if value.startswith("["):
        end = value.rfind("]:")
        if end >= 0:
            return value[1:end], value[end + 2:]
    if ":" not in value:
        return value, "unavailable"
    address, port = value.rsplit(":", 1)
    return address, port


def decode_processes(text: str) -> list[tuple[str, str]]:
    pairs = []
    for name, pid in PROCESS_RE.findall(text):
        name = re.sub(r'\\(["\\])', r'\1', name)
        pairs.append((name[:128] or "unavailable", pid))
    return pairs or [("unavailable", "unavailable")]


def classify_exposure(address: str) -> tuple[str, str]:
    host = address.split("%", 1)[0]
    if host in {"*", "0.0.0.0", "::"}:
        return "wildcard", "all"
    try:
        parsed = ipaddress.ip_address(host)
    except ValueError:
        return "unknown", "unknown"
    if parsed.is_loopback:
        return "loopback", "lo"
    if parsed.is_link_local:
        return "link_local", "scoped" if "%" in address else "unknown"
    return ("private" if parsed.is_private else "public", "unknown")


def parse_ss_output(output: str, metadata_available: bool) -> list[dict[str, str]]:
    inventory: list[dict[str, str]] = []
    for line in output.splitlines():
        columns = line.split(None, 6)
        if len(columns) < 6:
            continue
        protocol, state = columns[0].lower(), columns[1].upper()
        if protocol not in {"tcp", "udp"}:
            continue
        local_address, local_port = split_endpoint(columns[4])
        peer_address, peer_port = split_endpoint(columns[5])
        process_text = columns[6] if len(columns) > 6 else ""
        processes = decode_processes(process_text) if metadata_available else [("unavailable", "unavailable")]
        exposure, interface = classify_exposure(local_address)
        if "%" in local_address:
            interface = local_address.rsplit("%", 1)[1]
        for process_name, pid in processes:
            inventory.append({
                "protocol": protocol,
                "socket_state": state,
                "local_address": local_address,
                "local_port": local_port,
                "peer_address": peer_address,
                "peer_port": peer_port,
                "process_name": process_name,
                "pid": pid,
                "interface": interface,
                "exposure": exposure,
            })
    return inventory


def address_interfaces() -> dict[str, str]:
    """Read local interface addresses using iproute2; no elevated access needed."""
    try:
        result = subprocess.run(["/usr/sbin/ip", "-j", "address"], capture_output=True,
                                text=True, timeout=2, check=True)
        interfaces: dict[str, str] = {}
        for item in json.loads(result.stdout):
            for info in item.get("addr_info", []):
                local = info.get("local")
                if local:
                    interfaces[local] = item.get("ifname", "unknown")
        return interfaces
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        return {}


def docker_port_map() -> dict[str, str]:
    """Map published host ports to container names without reading env/config."""
    try:
        result = subprocess.run(["/usr/bin/docker", "ps", "--format", "{{.Names}}|{{.Ports}}"],
                                capture_output=True, text=True, timeout=3, check=True)
    except (OSError, subprocess.SubprocessError):
        return {}
    mapping: dict[str, str] = {}
    for line in result.stdout.splitlines():
        name, _, ports = line.partition("|")
        for host_port in re.findall(r"(?:\[[^]]+\]|[^,\s:]+):(\d+)->", ports):
            mapping.setdefault(host_port, name[:128])
    return mapping


def enrich_inventory(rows: list[dict[str, str]], service_map: dict, interfaces: dict[str, str], containers: dict[str, str]) -> None:
    by_port = service_map.get("ports", {})
    by_process = service_map.get("processes", {})
    for row in rows:
        ip = row["local_address"].split("%", 1)[0]
        if row["interface"] == "unknown" and ip in interfaces:
            row["interface"] = interfaces[ip]
        container = containers.get(row["local_port"], "")
        row["container_name"] = container or "unavailable"
        configured = by_port.get(f"{row['protocol']}:{row['local_port']}", {})
        process_app = by_process.get(row["process_name"], {})
        row["application_name"] = configured.get("application_name") or (container or process_app.get("application_name") or row["process_name"])
        row["browser_url"] = configured.get("browser_url", "")
        row["availability"] = "available"


def run_ss(use_sudo: bool = True, runner: Callable = subprocess.run) -> tuple[str, bool, str]:
    base = [SS_BIN, "-H", "-ltnup"]
    if use_sudo:
        try:
            result = runner([SUDO_BIN, "-n", *base], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return result.stdout, True, "ok"
            sudo_error = (result.stderr or "").lower()
        except (OSError, subprocess.SubprocessError) as exc:
            sudo_error = type(exc).__name__.lower()
    else:
        sudo_error = "sudo_disabled"
    try:
        result = runner(base, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return result.stdout, False, "process_metadata_unavailable"
        return "", False, "ss_failed"
    except (OSError, subprocess.SubprocessError):
        return "", False, "ss_failed"


def key_for_listener(row: dict[str, str]) -> str:
    # Include bind address so loopback-to-wildcard changes are detected as a new exposure.
    return f"{row['protocol']}:{row['local_port']}:{row['local_address']}"


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check_application(url: str, app: str, port: str, timeout: float = 2.0) -> dict:
    """HEAD-check an explicitly allowlisted URL; validate TLS and do not follow redirects."""
    status_code = 0
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "KaliSocketInventory/1.0"}, method="HEAD")
        opener = urllib.request.build_opener(NoRedirectHandler())
        with opener.open(request, timeout=timeout) as response:
            status_code = int(response.status)
    except urllib.error.HTTPError as exc:
        # A real HTTP response (including 401/403/404) proves the app answered.
        status_code = int(exc.code)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        pass
    return {"application_name": app, "local_port": str(port), "browser_url": url,
            "status_code": status_code, "up": int(100 <= status_code < 600)}


def check_allowlisted_applications(config: dict) -> list[dict]:
    checks = []
    ports = config.get("ports", {})
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(check_application, item["browser_url"], item["application_name"], key.split(":", 1)[1])
                   for key, item in ports.items() if item.get("browser_url", "").startswith(("http://", "https://"))]
        for future in futures:
            try:
                checks.append(future.result(timeout=3))
            except Exception:
                continue
    return checks


class InventoryCollector:
    def __init__(self, state_path: Path, config_path: Path, use_sudo: bool = True,
                 ss_runner: Callable = run_ss, now: Callable[[], float] = time.time):
        self.state_path = state_path
        self.config_path = config_path
        self.use_sudo = use_sudo
        self.ss_runner = ss_runner
        self.now = now
        self.lock = threading.Lock()
        self.state = self._read_state()

    def _read_state(self) -> dict:
        try:
            value = json.loads(self.state_path.read_text())
            if isinstance(value, dict):
                value.setdefault("baseline_initialized", False)
                value.setdefault("listeners", {})
                value.setdefault("events", [])
                version = int(value.get("schema_version", 1))
                if version < 2:
                    # Old snapshots collapsed multiple bind addresses under one port key.
                    # Reset once to avoid turning the richer baseline into false new-port alerts.
                    value["baseline_initialized"] = False
                    value["listeners"] = {}
                    value["events"] = []
                value["schema_version"] = 2
                return value
        except (OSError, json.JSONDecodeError):
            pass
        return {"schema_version": 2, "baseline_initialized": False, "listeners": {}, "events": []}

    def _write_state(self) -> None:
        self.state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.state_path.parent, 0o700)
        fd, name = tempfile.mkstemp(prefix="socket-inventory-", dir=self.state_path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(self.state, stream, separators=(",", ":"))
                stream.write("\n")
            os.chmod(name, 0o600)
            os.replace(name, self.state_path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def collect(self) -> dict:
        with self.lock:
            text, metadata, status = self.ss_runner(self.use_sudo)
            now = self.now()
            config = json.loads(self.config_path.read_text())
            rows = parse_ss_output(text, metadata) if status != "ss_failed" else []
            limit = max(1, int(config.get("max_inventory_rows", 2048)))
            truncated = len(rows) > limit
            rows = rows[:limit]
            enrich_inventory(rows, config, address_interfaces(), docker_port_map())
            unique = {}
            for row in rows:
                unique.setdefault(key_for_listener(row), row)
            current = unique
            socket_endpoints = {}
            for row in rows:
                endpoint = tuple(row[k] for k in ("protocol", "socket_state", "local_address", "local_port", "peer_address", "peer_port"))
                socket_endpoints.setdefault(endpoint, row)
            previous = self.state.get("listeners", {})
            events = self.state.get("events", [])
            if status != "ss_failed" and not truncated and self.state.get("baseline_initialized"):
                for change, keys in (("new", current.keys() - previous.keys()),
                                     ("disappeared", previous.keys() - current.keys())):
                    for key in keys:
                        row = dict(current[key] if change == "new" else previous[key])
                        row["availability"] = "available" if change == "new" else "disappeared"
                        events.append({"change": change, "row": row, "timestamp": now})
            if status != "ss_failed" and not truncated:
                self.state["listeners"] = current
                self.state["baseline_initialized"] = True
            ttl = float(config.get("change_event_ttl_seconds", 900))
            self.state["events"] = [e for e in events if now - float(e.get("timestamp", 0)) <= ttl][-500:]
            self._write_state()
            expected = config.get("expected_listeners", [])
            expected_status = []
            active_ports = {(row["protocol"], row["local_port"]) for row in rows}
            for item in expected if status != "ss_failed" and not truncated else []:
                key = (item["protocol"].lower(), str(item["port"]))
                expected_status.append({**item, "present": key in active_ports})
            return {"rows": rows, "sockets": list(socket_endpoints.values()), "metadata": metadata,
                    "status": status, "timestamp": now, "events": [dict(e) for e in self.state["events"]], "truncated": truncated,
                    "initialized": self.state["baseline_initialized"], "expected": expected_status,
                    "application_health": check_allowlisted_applications(config) if status != "ss_failed" else []}


def prom_escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def metric(name: str, help_text: str, labels: list[str], samples: list[tuple[dict, float]]) -> list[str]:
    lines = [f"# HELP {name} {help_text}", f"# TYPE {name} gauge"]
    for values, number in samples:
        rendered = ",".join(f'{label}="{prom_escape(values.get(label, ""))}"' for label in labels)
        selector = f"{{{rendered}}}" if rendered else ""
        lines.append(f"{name}{selector} {number:g}")
    return lines


def render_metrics(data: dict) -> bytes:
    rows = data["rows"]
    identities = ["protocol", "socket_state", "local_address", "local_port", "peer_address", "peer_port",
                  "process_name", "pid", "interface", "exposure", "application_name", "browser_url", "container_name", "availability"]
    out: list[str] = []
    out += metric("kali_socket_inventory_last_seen_timestamp_seconds", "Unix time this socket was last observed; row presence means available.", identities,
                  [(r, data["timestamp"]) for r in rows])
    out += metric("kali_socket_inventory_scrape_success", "Whether the ss inventory command succeeded.", [], [({}, 0 if data["status"] == "ss_failed" else 1)])
    out += metric("kali_socket_inventory_process_metadata_available", "Whether elevated ss returned process ownership metadata.", [], [({}, int(data["metadata"]) if data["status"] != "ss_failed" else 0)])
    out += metric("kali_socket_inventory_baseline_initialized", "Whether a prior successful inventory exists for change detection.", [], [({}, int(data["initialized"]))])
    out += metric("kali_socket_inventory_truncated", "Whether the inventory exceeded the configured row cap.", [], [({}, int(data.get("truncated", False)))])
    counts = {}
    for row in data["sockets"]:
        key = (row["protocol"], row["socket_state"])
        counts[key] = counts.get(key, 0) + 1
    out += metric("kali_socket_inventory_sockets", "Unique local socket endpoints by protocol and state.", ["protocol", "socket_state"],
                  [({"protocol": p, "socket_state": s}, n) for (p, s), n in counts.items()])
    latest_events = {}
    event_labels = ["change", *identities]
    for event in data["events"]:
        event_values = {"change": event["change"], **event["row"]}
        event_key = tuple(event_values.get(k, "") for k in event_labels)
        if event_key not in latest_events or event["timestamp"] > latest_events[event_key]["timestamp"]:
            latest_events[event_key] = {"labels": event_values, "timestamp": float(event["timestamp"])}
    changes = [(item["labels"], 1) for item in latest_events.values()]
    change_times = [(item["labels"], item["timestamp"]) for item in latest_events.values()]
    out += metric("kali_socket_listener_change", "Listeners newly discovered or disappeared within the configured event TTL.", event_labels, changes)
    out += metric("kali_socket_listener_change_timestamp_seconds", "Unix time of each listener discovery or disappearance event.", event_labels, change_times)
    expected_samples = []
    for item in data["expected"]:
        expected_samples.append(({"protocol": item["protocol"].lower(), "local_port": str(item["port"]), "expected_service": item.get("service", "important")},
                                 int(item["present"])))
    out += metric("kali_socket_listener_expected_up", "Availability of configured important protocol/port listeners.", ["protocol", "local_port", "expected_service"], expected_samples)
    health_labels = ["application_name", "local_port", "browser_url", "status_code"]
    health_samples = [({k: item[k] for k in health_labels}, item["up"]) for item in data.get("application_health", [])]
    out += metric("kali_socket_inventory_application_health", "Reachability of explicitly allowlisted HTTP(S) application URLs; HEAD only, no redirects, TLS certificate validation enabled.", health_labels, health_samples)
    out += metric("kali_socket_inventory_application_health_status_code", "Last HTTP status code; zero means no HTTP response or TLS/connection failure.", ["application_name", "local_port", "browser_url"], [({k: item[k] for k in ("application_name", "local_port", "browser_url")}, item["status_code"]) for item in data.get("application_health", [])])
    out += metric("kali_socket_inventory_last_scrape_timestamp_seconds", "Unix time of the most recent inventory attempt.", [], [({}, data["timestamp"])])
    return ("\n".join(out) + "\n").encode()


class MetricsHandler(BaseHTTPRequestHandler):
    collector: InventoryCollector
    server_version = "KaliSocketInventoryExporter/1.0"
    sys_version = ""

    def do_GET(self):
        if self.path != "/metrics":
            self.send_error(404)
            return
        payload = render_metrics(self.collector.collect())
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        return


class ThreadingUnixHTTPServer(ThreadingMixIn, UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default=str(Path.home() / ".local/share/kali-socket-inventory/metrics.sock"))
    parser.add_argument("--state", default=str(Path.home() / ".local/share/kali-socket-inventory/state.json"))
    parser.add_argument("--config", default=str(Path(__file__).resolve().parents[1] / "config.json"))
    parser.add_argument("--no-sudo", action="store_true", help="Do not try the narrowly scoped sudo ss command")
    args = parser.parse_args()
    path = Path(args.socket)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.connect(str(path))
        except OSError:
            path.unlink(missing_ok=True)
        else:
            raise SystemExit("metrics Unix socket is already active")
        finally:
            probe.close()
    collector = InventoryCollector(Path(args.state), Path(args.config), use_sudo=not args.no_sudo)
    handler = type("BoundMetricsHandler", (MetricsHandler,), {"collector": collector})
    server = ThreadingUnixHTTPServer(str(path), handler)
    os.chmod(path, 0o666)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
