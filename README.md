# Kali Command Center

Local, read-only observability for the Kali host, Docker workloads, confirmed lab services, and configured projects. This implementation extends the existing `kind-devsecops` Prometheus/Grafana stack. It does not create another Kubernetes cluster or monitoring stack.

## Current implementation stage

- Docker container metrics exporter listens on the kind Docker bridge at `172.22.0.1:19100`; a hardened user service starts it.
- Host metrics use the existing Netdata agent on `172.22.0.1:19999` and a filtered Prometheus `ServiceMonitor`. Netdata still requires a root-owned listener restriction; see `docs/IMPLEMENTATION-STATUS.md`.
- Project registry is explicit. Unconfigured projects remain unknown/unconfigured. Only allowlisted loopback probes are supported. Project source code is never executed.
- Prometheus scrape interval for these host endpoints is 30 seconds.

## Files

- `config/projects.yaml`: project registry, explicit checks, and discovery policy.
- `kubernetes/host-metrics-scrape.yaml`: Service, Endpoints, and ServiceMonitor resources.
- `scripts/`: local exporters and discovery tools.
- `dashboards/`: Grafana JSON dashboards.
- `alerts/`: local Prometheus alert rules.
- `systemd/user/`: user services.

## Safety

No credentials belong in this repository. Do not commit Helm release secrets, `.env` files, API tokens, private keys, local TSDB backups, or Grafana databases. The endpoint bind addresses are restricted to the kind bridge. Do not mount the Docker socket into a container. Do not scan external networks, start projects, modify firewall rules, or remove Docker data.
