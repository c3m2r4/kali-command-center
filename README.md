# Kali Command Center

A local, read-only operations view for the Kali host, its Docker containers, confirmed projects, and the existing `kind-devsecops` monitoring cluster. It extends the existing Prometheus/Grafana installation and does not install a second stack.

## Live services

- Grafana: <http://127.0.0.1:13000>
- Prometheus: <http://127.0.0.1:19090>
- Kubernetes Dashboard: <https://127.0.0.1:8443>
- Port forwards run as user systemd services and bind to loopback only.

The enabled Grafana dashboards use UID paths:

- `kali-executive-overview`
- `kali-system-performance`
- `kali-services-ports`
- `kali-docker-containers`
- `kali-project-command-center`
- `kali-security-lab`
- `kali-storage-capacity`
- `kali-network-connectivity`
- `kali-alerts-reliability`
- Existing: `devsecops-control-plane-advanced`, `docker-containers-overview`, `trivy-operator-overview`

Example: `http://127.0.0.1:13000/d/kali-executive-overview/kali-executive-overview`.

## Data path

- Prometheus scrapes existing Kubernetes components and node-exporter.
- The existing user-level `docker-container-exporter.service` reads container inventory/stats and host-local Netdata metrics, plus read-only project metadata/checks. It updates the existing `docker-host-container-metrics` ConfigMap every 60 seconds; node-exporter’s existing textfile collector exposes those samples to Prometheus.
- The project registry is `config/projects.yaml`. New discoveries begin as unconfigured. Only explicit loopback HTTP/TCP checks run. Source code is never executed; no external network probes occur.
- Netdata metrics are filtered to CPU, memory/pressure, disk, inode, network, and sensor families. Netdata is fetched through host loopback; the pre-existing Netdata listener still binds all interfaces and needs the root-owned hardening step in the runbook.
- Alerts use the existing PrometheusRule/Alertmanager path and have no external receivers configured.

## Operations

```bash
systemctl --user status docker-container-exporter.service
systemctl --user status kali-grafana-forward.service kali-prometheus-forward.service kali-dashboard-forward.service
systemctl --user restart docker-container-exporter.service
kubectl -n default get servicemonitor,prometheusrule
kubectl -n default get cm docker-host-container-metrics
curl -fsS http://127.0.0.1:13000/api/health
curl -fsS http://127.0.0.1:19090/-/healthy
curl -fsSG http://127.0.0.1:19090/api/v1/query --data-urlencode 'query=kali_cc_project_state'
curl -fsSG http://127.0.0.1:19090/api/v1/query --data-urlencode 'query=up'
```

To add a project, add an entry in `config/projects.yaml`, begin with `monitoring: unconfigured`, and use only an explicit `127.0.0.1`/`::1` check. Validate YAML before restarting the publisher. Registry and dashboards are provisioned without embedding credentials.

## Resource and storage status

The user-level publisher reads the local Docker daemon through the existing CLI, fetches Netdata over loopback, and uses the existing Kubernetes ConfigMap publishing path. The project metrics snapshot is roughly 115 KiB and remains below ConfigMap size limits. Prometheus currently retains 10 days but has no TSDB size ceiling and uses `emptyDir`; Grafana also has ephemeral pod storage. Persistent claims were not enabled because moving the active TSDB without its admin snapshot endpoint or a safe offline copy would discard current history. See `docs/IMPLEMENTATION-STATUS.md` for the migration and Netdata hardening follow-ups.

## Backup and rollback

A private pre-change backup is outside the repository at `/home/camara/.local/share/kali-command-center/backups/20261017-233205` (directory mode 0700, files mode 0600; no Kubernetes Secrets were exported). Roll back the PrometheusRule with `kubectl delete -f alerts/kali-command-center-rules.yaml`; restore dashboard ConfigMaps from the backup or delete `kcc-dashboard-*` ConfigMaps. Remove the node-exporter textfile publisher extension by restoring the backed-up publisher script and restarting `docker-container-exporter.service`. User port forwards can be stopped/disabled individually with `systemctl --user disable --now kali-<service>-forward.service`.

No Docker pruning, project starts, firewall changes, packages, application configuration changes, or remote lab changes were made.
