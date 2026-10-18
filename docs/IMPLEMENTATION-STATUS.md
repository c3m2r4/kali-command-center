# Implementation status

## Completed

- Pre-change Helm/Kubernetes backup is outside the repository with mode 0700/0600: `/home/camara/.local/share/kali-command-center/backups/20261017-233205`. No Kubernetes Secret objects were exported.
- Existing user-level Docker metrics publisher now also emits local Netdata and project metrics through the existing node-exporter textfile ConfigMap path. The ConfigMap is approximately 115 KiB; Prometheus accepts the resulting metrics.
- Prometheus queries return real project inventory, Docker inventory, local service checks, host Netdata metrics, systemd state and capacity samples.
- Nine Kali Command Center dashboards are provisioned through labeled Grafana ConfigMaps, in addition to the existing DevSecOps, Docker and Trivy dashboards.
- PrometheusRule has ten locally evaluated rules for scrape/publisher health, stale project metrics, failing local probes, stopped registered containers, degraded projects, host CPU/memory pressure, and root disk/inode pressure. Alertmanager has no external receiver configured.
- Grafana (`127.0.0.1:13000`), Prometheus (`127.0.0.1:19090`) and Kubernetes Dashboard (`127.0.0.1:8443`) port forwards run as enabled user systemd services. Grafana and Prometheus health endpoints return success.
- Eight `/var/www` projects plus AEGIS, Floci, Mythic, GOAD and existing monitoring services are represented explicitly. Unknown/unconfigured projects are not reported as healthy.

## Pending, with reason

- **Netdata listener hardening:** the pre-existing listener still binds all interfaces. The host-side publisher fetches Netdata over loopback, so no new ingress is needed. Restricting the listener requires editing a root-owned file and restarting Netdata. This shell has no noninteractive sudo authorization; the exact command is in `docs/OPERATIONS-RUNBOOK.md`.
- **Persistent TSDB/Grafana storage and size cap:** Prometheus uses `/prometheus` on `emptyDir`, has 10-day retention and an unset size limit (`0B`). Its admin snapshot API is disabled and the current image lacks shell/tar utilities. A pod restart during a PVC migration would erase the only current copy of the TSDB. Grafana also uses ephemeral storage. No destructive or lossy rollout was made; plan a maintenance migration with a verified TSDB snapshot/backup first.
- **Grafana API validation:** Grafana is authenticated. Its health endpoint succeeds and the in-cluster dashboard sidecar reports provisioning reloads with HTTP 200, but API search was not attempted without credentials. Dashboard JSON parses, uses the existing Prometheus datasource UID, and all dashboard panel PromQL expressions passed Prometheus query parsing.
- **Network dashboard details:** current Netdata filter provides interface throughput and packet metrics; external DNS/ICMP probes, TLS expiry, broad process metrics and centralized logs are not configured. No remote networks are probed.

## Current resource guardrails

No second Prometheus/Grafana stack, Loki, cAdvisor, package installs, firewall edits, container cleanup, project starts, or application workload changes. Metrics are local-only and bounded by explicit project registration, filtered Netdata families, 60-second ConfigMap publishing, and the current 10-day Prometheus retention.

At the last validation snapshot, HackAfrica was correctly marked degraded because its API container was restarting; no other project was labeled healthy without a passing configured probe or running registered containers.
