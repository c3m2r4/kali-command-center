#!/usr/bin/python3
"""Read-only local project, service, Git, and capacity metrics for Prometheus."""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import yaml
except ImportError as exc:
    raise SystemExit('PyYAML is required; use the system package already present on Kali.') from exc

BIND = '172.22.0.1'
PORT = 19101
REGISTRY = Path('/home/camara/Projects/kali-command-center/config/projects.yaml')
CACHE_SECONDS = 25
GIT_REFRESH_SECONDS = 300
SIZE_REFRESH_SECONDS = 900
ALLOWED_PROBE_HOSTS = {'127.0.0.1', '::1', 'localhost'}
TECH_MARKERS = [
    ('docker-compose.yml', 'Docker Compose'), ('compose.yaml', 'Docker Compose'),
    ('Dockerfile', 'Container'), ('pyproject.toml', 'Python'),
    ('requirements.txt', 'Python'), ('manage.py', 'Python web app'),
    ('composer.json', 'PHP/Composer'), ('artisan', 'Laravel'),
    ('package.json', 'Node.js'), ('go.mod', 'Go'), ('Cargo.toml', 'Rust'),
    ('pom.xml', 'Java/Maven'), ('index.html', 'Static web'), ('_config.yml', 'Static site'),
]

_lock = threading.Lock()
_cache = {'until': 0.0, 'body': b''}
_refresh_guard = threading.Lock()
_git_cache: dict[str, tuple[float, str, bool, float]] = {}
_size_cache: dict[str, tuple[float, int, bool]] = {}
_size_queue_lock = threading.Lock()
_size_pending: set[str] = set()
_size_worker_active = False
_last_success: dict[str, float] = {}
_last_failure: dict[str, float] = {}


def esc(value: object) -> str:
    return str(value).replace('\\', '\\\\').replace('\n', '\\n').replace('"', '\\"')


def metric(name: str, labels: dict[str, object], value: object) -> str:
    label_text = ','.join(f'{k}="{esc(v)}"' for k, v in labels.items())
    return f'{name}{{{label_text}}} {value}'


def run(args: list[str], timeout: int = 8) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def git_data(path: str) -> tuple[str, bool, float]:
    now = time.time()
    item = _git_cache.get(path)
    if item and now - item[0] < GIT_REFRESH_SECONDS:
        return item[1], item[2], item[3]
    branch, dirty, commit = 'unknown', False, 0.0
    if path and Path(path, '.git').exists():
        try:
            b = run(['git', '-C', path, 'branch', '--show-current'], timeout=2)
            if b.returncode == 0:
                branch = b.stdout.strip() or 'detached'
            s = run(['git', '-C', path, 'diff-index', '--quiet', 'HEAD', '--'], timeout=2)
            dirty = s.returncode == 1
            c = run(['git', '-C', path, 'log', '-1', '--format=%ct'], timeout=2)
            try:
                commit = float(c.stdout.strip()) if c.returncode == 0 else 0.0
            except ValueError:
                commit = 0.0
        except (subprocess.TimeoutExpired, OSError):
            pass
    _git_cache[path] = (now, branch, dirty, commit)
    return branch, dirty, commit


def project_size(path: str) -> tuple[int, bool]:
    now = time.time()
    item = _size_cache.get(path)
    if item and now - item[0] < SIZE_REFRESH_SECONDS:
        return item[1], item[2]
    if item is None:
        # Return unknown immediately; the one-filesystem metadata scan runs outside scrape.
        _size_cache[path] = (now, 0, False)
        schedule_project_size_refresh(path)
        return 0, False
    # Keep the last completed sample visible while the sequential worker refreshes it.
    if now - item[0] >= SIZE_REFRESH_SECONDS:
        _size_cache[path] = (now, item[1], item[2])
        schedule_project_size_refresh(path)
    return item[1], item[2]

def schedule_project_size_refresh(path: str) -> None:
    global _size_worker_active
    with _size_queue_lock:
        _size_pending.add(path)
        if _size_worker_active:
            return
        _size_worker_active = True
    threading.Thread(target=refresh_project_sizes, daemon=True).start()

def refresh_project_sizes() -> None:
    global _size_worker_active
    while True:
        with _size_queue_lock:
            if not _size_pending:
                _size_worker_active = False
                return
            path = sorted(_size_pending)[0]
            _size_pending.remove(path)
        refresh_project_size(path)

def refresh_project_size(path: str) -> None:
    now = time.time()
    if not path or not Path(path).is_dir():
        result = (now, 0, False)
    else:
        # du reads filesystem metadata only; it does not open or execute project files.
        try:
            r = run(['/usr/bin/du', '-sb', '--one-file-system', '--', path], timeout=60)
            size = int(r.stdout.split('\t', 1)[0]) if r.stdout.strip() else 0
            # du can report an accessible partial size when permissions block some files; expose it but mark unknown.
            result = (time.time(), size, r.returncode == 0)
        except (ValueError, IndexError, subprocess.TimeoutExpired, OSError):
            result = (time.time(), 0, False)
    _size_cache[path] = result


def probe(check: dict) -> tuple[int, float, str, int]:
    target = str(check.get('target', ''))
    kind = check.get('type')
    started = time.monotonic()
    parsed = urllib.parse.urlsplit(target) if kind == 'http' else None
    host = parsed.hostname if parsed else target.rsplit(':', 1)[0].strip('[]')
    if host not in ALLOWED_PROBE_HOSTS:
        return 0, time.monotonic() - started, 'target_not_allowlisted', 0
    try:
        if kind == 'tcp':
            port = int(target.rsplit(':', 1)[1])
            with socket.create_connection((host, port), timeout=2):
                pass
            return 1, time.monotonic() - started, '', 0
        if kind != 'http' or parsed is None or parsed.scheme not in ('http', 'https'):
            return 0, time.monotonic() - started, 'invalid_check', 0
        # Refuse redirects so the registry cannot make the exporter contact remote hosts.
        opener = urllib.request.build_opener(urllib.request.HTTPHandler(), urllib.request.HTTPSHandler(), _NoRedirect())
        req = urllib.request.Request(target, headers={'User-Agent': 'kali-command-center-health/1'})
        try:
            response = opener.open(req, timeout=3)
            code = response.status
            response.close()
        except urllib.error.HTTPError as e:
            code = e.code
        return int(200 <= code < 400), time.monotonic() - started, '' if 200 <= code < 400 else f'http_{code}', code
    except TimeoutError:
        return 0, time.monotonic() - started, 'timeout', 0
    except ConnectionRefusedError:
        return 0, time.monotonic() - started, 'connection_refused', 0
    except urllib.error.URLError as e:
        reason = getattr(e, 'reason', None)
        return 0, time.monotonic() - started, 'timeout', 0 if isinstance(reason, TimeoutError) else 'connection_error'
    except Exception as e:
        return 0, time.monotonic() - started, type(e).__name__.lower(), 0


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def docker_rows() -> list[dict[str, str]]:
    r = run(['/usr/bin/docker', 'ps', '-a', '--format', '{{.Names}}\t{{.State}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}'])
    if r.returncode != 0:
        return []
    rows = []
    for line in r.stdout.splitlines():
        fields = line.split('\t', 4)
        if len(fields) == 5:
            rows.append(dict(zip(('name', 'state', 'status', 'image', 'ports'), fields)))
    return rows


def docker_available() -> bool:
    return run(['/usr/bin/docker', 'info', '--format', '{{.ServerVersion}}'], timeout=10).returncode == 0


def unit_state(unit: str, user: bool = False) -> str:
    args = ['systemctl'] + (['--user'] if user else []) + ['show', unit, '-p', 'ActiveState', '--value']
    r = run(args)
    value = r.stdout.strip().lower()
    return value if r.returncode == 0 and value else 'unknown'


def discover(root: str, configured: set[str]) -> list[tuple[str, str]]:
    result = []
    p = Path(root)
    if not p.is_dir():
        return result
    try:
        for child in p.iterdir():
            if child.name.startswith('.') or not child.is_dir() or str(child) in configured:
                continue
            tech = 'unknown'
            for marker, label in TECH_MARKERS:
                if (child / marker).exists():
                    tech = label
                    break
            result.append((child.name, tech))
    except OSError:
        return result
    return result


def collect() -> bytes:
    now = time.time()
    with _lock:
        if now < _cache['until']:
            return _cache['body']
        cfg = yaml.safe_load(REGISTRY.read_text()) or {}
        projects = list(cfg.get('projects', [])) + list(cfg.get('additional_projects', []))
        checks = cfg.get('policy', {})
        rows = docker_rows()
        by_name = {r['name']: r for r in rows}
        configured_paths = {p.get('path', '') for p in projects if p.get('path')}
        out: list[str] = []
        out += ['# HELP kali_cc_project_info Static project registry metadata.', '# TYPE kali_cc_project_info gauge']
        out += ['# HELP kali_cc_project_state Project state encoded as a one-hot state label.', '# TYPE kali_cc_project_state gauge']
        out += ['# HELP kali_cc_project_directory_exists Whether the registered source directory exists.', '# TYPE kali_cc_project_directory_exists gauge']
        out += ['# HELP kali_cc_project_git_dirty Whether tracked Git files have uncommitted changes.', '# TYPE kali_cc_project_git_dirty gauge']
        out += ['# HELP kali_cc_project_last_commit_timestamp_seconds Last local commit time as Unix time.', '# TYPE kali_cc_project_last_commit_timestamp_seconds gauge']
        out += ['# HELP kali_cc_project_size_bytes Directory size sampled periodically with du.', '# TYPE kali_cc_project_size_bytes gauge']
        out += ['# HELP kali_cc_project_size_known Whether directory size measurement succeeded.', '# TYPE kali_cc_project_size_known gauge']
        out += ['# HELP kali_cc_container_running Whether a registered Docker container is running.', '# TYPE kali_cc_container_running gauge']
        out += ['# HELP kali_cc_container_state Container current state encoded as a one-hot state label.', '# TYPE kali_cc_container_state gauge']
        out += ['# HELP kali_cc_health_check_up Whether the explicit local service check succeeded.', '# TYPE kali_cc_health_check_up gauge']
        out += ['# HELP kali_cc_health_check_status_code HTTP status code; zero for TCP checks or failed requests.', '# TYPE kali_cc_health_check_status_code gauge']
        out += ['# HELP kali_cc_health_check_response_seconds Time taken by the most recent local service check.', '# TYPE kali_cc_health_check_response_seconds gauge']
        out += ['# HELP kali_cc_health_check_last_success_timestamp_seconds Last successful check time.', '# TYPE kali_cc_health_check_last_success_timestamp_seconds gauge']
        out += ['# HELP kali_cc_health_check_last_failure_timestamp_seconds Last failed check time.', '# TYPE kali_cc_health_check_last_failure_timestamp_seconds gauge']
        out += ['# HELP kali_cc_health_check_error Last failure category, without response body or sensitive data.', '# TYPE kali_cc_health_check_error gauge']
        out += ['# HELP kali_cc_systemd_unit_state Systemd unit state encoded as a one-hot state label.', '# TYPE kali_cc_systemd_unit_state gauge']
        out += ['# HELP kali_cc_systemd_failed_units Number of failed system service units.', '# TYPE kali_cc_systemd_failed_units gauge']
        out += ['# HELP kali_cc_docker_daemon_available Whether Docker CLI can reach the daemon.', '# TYPE kali_cc_docker_daemon_available gauge']
        out += ['# HELP kali_cc_vmware_running_vms Number of locally running VMware VMs, or -1 if unavailable.', '# TYPE kali_cc_vmware_running_vms gauge']
        out += ['# HELP kali_cc_discovered_project_info A directory found during safe top-level project discovery.', '# TYPE kali_cc_discovered_project_info gauge']

        state_for: dict[str, str] = {}
        for project in projects:
            name = str(project.get('name', 'unknown'))
            path = str(project.get('path', ''))
            mode = str(project.get('monitoring', 'unconfigured'))
            exists = int(bool(path and Path(path).is_dir())) if path else 1
            branch, dirty, commit = git_data(path)
            labels = {'project': name, 'kind': project.get('kind', 'project'), 'technology': project.get('technology', 'unknown'), 'monitoring': mode, 'git_branch': branch}
            out.append(metric('kali_cc_project_info', labels, 1))
            out.append(metric('kali_cc_project_directory_exists', {'project': name}, exists))
            out.append(metric('kali_cc_project_git_dirty', {'project': name}, int(dirty)))
            out.append(metric('kali_cc_project_last_commit_timestamp_seconds', {'project': name}, commit))
            size, known = project_size(path) if path else (0, False)
            out.append(metric('kali_cc_project_size_bytes', {'project': name}, size))
            out.append(metric('kali_cc_project_size_known', {'project': name}, int(known)))

            assigned = list(project.get('containers', []))
            states = []
            for container in assigned:
                row = by_name.get(container)
                if row:
                    state = row['state'].lower()
                    status = row['status'].lower()
                    health = 'healthy' if '(healthy)' in status else ('unhealthy' if '(unhealthy)' in status else 'none')
                    out.append(metric('kali_cc_container_running', {'project': name, 'container': container}, int(state == 'running')))
                    out.append(metric('kali_cc_container_state', {'project': name, 'container': container, 'state': state, 'health': health, 'image': row['image']}, 1))
                    states.append(state)
                else:
                    out.append(metric('kali_cc_container_running', {'project': name, 'container': container}, 0))
                    out.append(metric('kali_cc_container_state', {'project': name, 'container': container, 'state': 'not_found', 'health': 'unknown', 'image': 'unknown'}, 1))
                    states.append('not_found')

            check_results = []
            for check in project.get('checks', []):
                cname = str(check.get('name', 'check'))
                target = str(check.get('target', ''))
                ok, duration, error, status_code = probe(check)
                key = f'{name}|{cname}'
                if ok:
                    _last_success[key] = now
                else:
                    _last_failure[key] = now
                cl = {'project': name, 'check': cname, 'type': str(check.get('type', 'unknown')), 'target': target}
                out.append(metric('kali_cc_health_check_up', cl, ok))
                out.append(metric('kali_cc_health_check_status_code', cl, status_code))
                out.append(metric('kali_cc_health_check_response_seconds', cl, f'{duration:.6f}'))
                out.append(metric('kali_cc_health_check_last_success_timestamp_seconds', cl, _last_success.get(key, 0)))
                out.append(metric('kali_cc_health_check_last_failure_timestamp_seconds', cl, _last_failure.get(key, 0)))
                if error:
                    out.append(metric('kali_cc_health_check_error', {**cl, 'error': error}, 1))
                check_results.append(ok)

            if mode != 'configured':
                state = 'unconfigured'
            elif any(s in ('restarting', 'dead', 'exited', 'not_found') for s in states):
                state = 'degraded' if any(s == 'restarting' for s in states) else 'stopped'
            elif any(not x for x in check_results):
                state = 'degraded'
            elif check_results or (states and all(s == 'running' for s in states)):
                state = 'healthy'
            else:
                state = 'unknown'
            state_for[name] = state
            out.append(metric('kali_cc_project_state', {'project': name, 'state': state}, 1))

        for root in cfg.get('discovery_roots', []):
            for name, tech in discover(str(root), configured_paths):
                if any(p.get('name') == name for p in projects):
                    continue
                out.append(metric('kali_cc_discovered_project_info', {'project': name, 'technology': tech, 'state': 'unconfigured'}, 1))
                out.append(metric('kali_cc_project_state', {'project': name, 'state': 'unconfigured'}, 1))

        for unit in ['docker.service', 'netdata.service', 'ssh.service', 'NetworkManager.service', 'systemd-networkd-wait-online.service']:
            state = unit_state(unit)
            out.append(metric('kali_cc_systemd_unit_state', {'unit': unit, 'state': state}, 1))
        for unit in ['docker-container-exporter.service', 'docker-container-metrics-http.service']:
            state = unit_state(unit, user=True)
            out.append(metric('kali_cc_systemd_unit_state', {'unit': unit, 'state': state}, 1))
        failed = run(['systemctl', '--failed', '--type=service', '--no-legend', '--plain'])
        failed_count = sum(1 for line in failed.stdout.splitlines() if line.strip()) if failed.returncode == 0 else -1
        out.append(metric('kali_cc_systemd_failed_units', {}, failed_count))
        out.append(metric('kali_cc_docker_daemon_available', {}, int(docker_available())))
        vmrun = shutil.which('vmrun')
        if vmrun:
            r = run([vmrun, 'list'], timeout=10)
            count = max(0, len([x for x in r.stdout.splitlines() if x.strip()]) - 1) if r.returncode == 0 else -1
        else:
            count = -1
        out.append(metric('kali_cc_vmware_running_vms', {}, count))
        body = ('\n'.join(out) + '\n').encode()
        _cache['body'], _cache['until'] = body, time.time() + CACHE_SECONDS
        return body


def refresh_cache() -> None:
    if not _refresh_guard.acquire(blocking=False):
        return
    try:
        collect()
    except Exception:
        pass
    finally:
        _refresh_guard.release()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/healthz':
            payload, status = b'ok\n', 200
        elif self.path == '/metrics':
            # Serve the most recent snapshot immediately; update it asynchronously.
            payload, status = _cache['body'] or b'# HELP kali_cc_exporter_ready Exporter has completed its first snapshot.\n# TYPE kali_cc_exporter_ready gauge\nkali_cc_exporter_ready 0\n', 200
            if time.time() >= _cache['until']:
                threading.Thread(target=refresh_cache, daemon=True).start()
        else:
            payload, status = b'not found\n', 404
        self.send_response(status)
        self.send_header('Content-Type', 'text/plain; version=0.0.4; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        return


if __name__ == '__main__':
    threading.Thread(target=refresh_cache, daemon=True).start()
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()
