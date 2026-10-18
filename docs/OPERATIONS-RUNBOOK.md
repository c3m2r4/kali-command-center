# Operations Runbook

## URLs

- Grafana: <http://127.0.0.1:13000>
- Prometheus: <http://127.0.0.1:19090>
- Kubernetes Dashboard: <https://127.0.0.1:8443>

Dashboards in Grafana: Kali Linux Executive Overview, Kali System Performance, Docker and Containers, Project Command Center, Cybersecurity Lab Infrastructure, Storage and Project Capacity, Network and Connectivity, Alerts and Reliability, plus the existing DevSecOps Control Plane, Docker Containers Advanced, and Trivy Operator dashboards.

## Routine checks

```bash
systemctl --user status docker-container-exporter.service
systemctl --user status kali-grafana-forward.service kali-prometheus-forward.service kali-dashboard-forward.service
systemctl --user restart docker-container-exporter.service
kubectl -n default get cm docker-host-container-metrics
kubectl -n default get servicemonitor,prometheusrule
kubectl -n default get pods
curl -fsS http://127.0.0.1:13000/api/health
curl -fsS http://127.0.0.1:19090/-/healthy
curl -fsSG http://127.0.0.1:19090/api/v1/query --data-urlencode 'query=kali_cc_project_state'
curl -fsSG http://127.0.0.1:19090/api/v1/query --data-urlencode 'query=netdata_system_cpu_percentage_average'
```

Run repository checks with `scripts/validate.sh`. Run safe host inventory with `scripts/discover.sh`; it omits environment variables and journal contents.

## Register a project

1. Add a `projects:` or `additional_projects:` item to `config/projects.yaml` with a name, existing directory, technology, kind, and `monitoring: unconfigured`.
2. Add container names only when confirmed from `docker ps -a`; add checks only for explicitly approved local endpoints on `127.0.0.1`, `::1`, or `localhost`.
3. Do not add credentials, environment contents, remote endpoints, or command execution. The exporter does not execute project code.
4. Restart `docker-container-exporter.service`; check that the ConfigMap updates, then query `kali_cc_project_info`, `kali_cc_project_state`, and `kali_cc_health_check_up`.

## Services and troubleshooting

- The user service `docker-container-exporter.service` publishes the Docker, project and filtered Netdata metrics ConfigMap every 60 seconds. Check logs with `journalctl --user -u docker-container-exporter.service -n 50 --no-pager`.
- Prometheus reads host/Docker/project metrics through the existing node-exporter textfile collector. The ConfigMap should contain `metrics.prom`; `node_textfile_scrape_error` should be `0`.
- Port-forward services bind only to loopback and restart automatically. Check them with `systemctl --user status kali-grafana-forward.service` and matching Prometheus/Dashboard services.
- New projects without explicit checks remain `unconfigured`; a source directory alone is not evidence of a running service.
- No logs are centrally collected. No external alert receiver is configured.

## Netdata listener hardening (requires root)

Netdata currently listens on all host interfaces. Its metrics are fetched by the host publisher over `127.0.0.1`; narrowing the listener will not interrupt that path. This shell did not have noninteractive sudo rights, so the change is prepared here for an interactive administrator terminal. First make a private backup and then restrict the listener to host loopback; the kind-bridge path is not needed because Prometheus no longer connects directly:

```bash
sudo cp -a /opt/netdata/etc/netdata/netdata.conf /opt/netdata/etc/netdata/netdata.conf.kcc-backup
sudo python3 - <<'PY'
from pathlib import Path
import re
p = Path('/opt/netdata/etc/netdata/netdata.conf')
s = p.read_text()
lines = s.splitlines()
start = next((i for i, line in enumerate(lines) if re.match(r'^\s*\[web\]\s*(?:#.*)?$', line)), None)
if start is None:
    lines += ['', '[web]', '    bind to = 127.0.0.1']
else:
    end = next((i for i in range(start + 1, len(lines)) if re.match(r'^\s*\[.*\]\s*(?:#.*)?$', lines[i])), len(lines))
    found = next((i for i in range(start + 1, end) if re.match(r'^\s*bind to\s*=', lines[i])), None)
    if found is None:
        lines.insert(start + 1, '    bind to = 127.0.0.1')
    else:
        lines[found] = '    bind to = 127.0.0.1'
p.write_text('\n'.join(lines) + '\n')
PY
sudo systemctl restart netdata.service
sudo ss -ltnp | grep ':19999'
```

Expected listener after restart: `127.0.0.1:19999`. If Netdata does not start or the dashboard loses host metrics, restore the saved config and restart the unit:

```bash
sudo cp -a /opt/netdata/etc/netdata/netdata.conf.kcc-backup /opt/netdata/etc/netdata/netdata.conf
sudo systemctl restart netdata.service
```

## Storage migration follow-up

Prometheus currently stores its 10-day TSDB in pod `emptyDir`, with no size cap; Grafana’s database is also ephemeral. Do not apply PVC changes by restarting Prometheus: that would lose the current TSDB. Schedule a maintenance window and create/verify a Prometheus snapshot or offline copy using an approved tool, then migrate to a bounded ext4-backed PVC and test rollback. Current `/mnt/vmstorage` free capacity is tight; do not place monitoring data there without a fresh capacity check. Avoid exFAT for the TSDB.

## Backup and rollback

Pre-change Kubernetes/Helm configuration backup: `/home/camara/.local/share/kali-command-center/backups/20261017-233205` (private directory, mode 0700; files mode 0600). It contains no Kubernetes Secrets. To disable the new local alert rules: `kubectl delete -f alerts/kali-command-center-rules.yaml`. Dashboard ConfigMaps are named `kcc-dashboard-*`; remove only those ConfigMaps to roll back the new dashboards. Restore the user publisher from the private backup or the pre-change file copy if needed, then restart `docker-container-exporter.service`. Disable a port forward with `systemctl --user disable --now kali-grafana-forward.service` (or the matching service).
