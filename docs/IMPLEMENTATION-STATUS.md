# Implementation status

- Pre-change Helm/Kubernetes backup is stored outside this repository with mode 0700/0600: `/home/camara/.local/share/kali-command-center/backups/20261017-233205`. No Kubernetes Secret objects were exported.
- Existing Docker metrics exporter is active as `docker-container-metrics-http.service`; `/metrics` returned 200 with 27 container inventory rows.
- Host scrape manifests are prepared; they are applied in staged validation.
- Netdata config is root-owned under `/opt/netdata/etc/netdata/netdata.conf`. This shell has no noninteractive sudo authorization. The Netdata listener restriction/restart is pending; no privilege bypass has been used.
- Grafana/Prometheus PVC migration is pending a safe data-preserving migration. The current Prometheus image has no `tar`, its admin snapshot API is disabled, and current metrics history has not been discarded.
