# Kali Sentinel socket inventory

Read-only inventory and Prometheus dashboard for the host output of `ss -ltnup`.
It inventories TCP `LISTEN` sockets and UDP sockets, local/peer endpoints, state,
process name/PID (when available), interface, exposure class, Docker published
port identity, a verified application URL allowlist, and last-seen time.

## Live deployment

- Executive overview: <http://localhost:13000/d/kali-sentinel-overview/kali-sentinel-7c-executive-overview?orgId=1&from=now-6h&to=now&timezone=browser&refresh=30s>. It summarizes live host, target, endpoint-check, DBCC scrape, event-rate, and disk telemetry; coverage notes distinguish missing data from healthy results.
- File integrity coverage: <http://localhost:13000/d/kali-sentinel-file-integrity/kali-sentinel-7c-file-integrity?orgId=1&from=now-6h&to=now&timezone=browser&refresh=30s>. It reports collector observations and clearly shows that no FIM event feed is currently exposed to Prometheus; service presence is not proof of configured monitoring.
- Grafana dashboard: <http://localhost:13000/d/kali-sentinel-sockets/kali-sentinel-listening-sockets?orgId=1&from=now-6h&to=now&timezone=browser&refresh=30s>
- Catalog companion: Linux Network Stack (node_exporter), <http://localhost:13000/d/linux-net-stack-nodeexp/linux-network-stack-node-exporter?orgId=1&from=now-6h&to=now&timezone=browser&refresh=30s>. This is based on [Grafana.com dashboard 25816](https://grafana.com/grafana/dashboards/25816-linux-network-stack-node-exporter/) and complements the listener inventory with kernel TCP/UDP/socket, conntrack, and softnet metrics.
- AppSec and API health: <http://localhost:13000/d/kali-sentinel-appsec/kali-sentinel-7c-application-and-api-security?orgId=1&from=now-6h&to=now&timezone=browser&refresh=30s>. This shows configured endpoint checks, HTTP status/latency, container restarts, and firing alerts; it does not provide request-level audit or authentication telemetry.
- Audit and monitoring health: <http://localhost:13000/d/kali-sentinel-audit-health/kali-sentinel-7c-audit-and-monitoring-health?orgId=1&from=now-6h&to=now&timezone=browser&refresh=30s>. It reports scrape health and collector heartbeat/event counters. A fresh heartbeat does not prove MariaDB audit-plugin state or event completeness.
- Database activity monitoring: <http://localhost:13000/d/kali-sentinel-dam/kali-sentinel-7c-database-activity-monitoring?orgId=1&from=now-6h&to=now&timezone=browser&refresh=30s>. It shows bounded event categories and collector status; detailed normalized records remain in DBCC.
- Database fleet: <http://localhost:13000/d/kali-sentinel-db-fleet/kali-sentinel-7c-database-fleet?orgId=1&from=now-6h&to=now&timezone=browser&refresh=30s>. It combines observed database/broker socket binds, exporter coverage, and bounded DBCC event metrics; socket presence is not a database health check.
- Prometheus target should appear as `kali-socket-inventory` at `172.22.0.2:19100`.
- Metrics endpoint is reachable only on the Kind control-plane network. The host
  exporter serves a private Unix socket in `~/.local/share/kali-socket-inventory`;
  an unprivileged, capability-dropped socat relay exposes it inside the Kind node.
  No host TCP port is opened and Grafana/Prometheus remain unprivileged.
- Port `19100` was checked free in the Kind control-plane network namespace; the
  exporter relay binds only inside that namespace. Validation confirmed no host
  TCP listener on `19100`. The initial live socket inventory found other active
  ports, so this avoids adding a competing host listener.
- The host has no scoped sudo permission at initial deployment. Therefore the
  current `ss` output may omit owners/PIDs; the exporter explicitly reports
  `process_name="unavailable"`, `pid="unavailable"`, and the
  `kali_socket_inventory_process_metadata_available` metric is `0`.

## Complete process metadata (optional)

Review `scripts/install.sh` before running it. It validates and installs one
sudoers entry for the current account, allowing only `/usr/bin/ss -H -ltnup`.
It does not grant a shell or general root access and does not run Grafana,
Prometheus, the exporter, or the relay as root. Then it installs/restarts the
user services and reapplies the dashboard/monitor resources:

```sh
cd ~/Projects/kali-command-center
./socket-monitoring/scripts/install.sh
```

If you do not want to grant this exact permission, the unprivileged inventory
continues to work and process data remains explicitly unavailable.

## Install/reconcile without sudo

```sh
cd ~/Projects/kali-command-center
./socket-monitoring/scripts/deploy-user.sh
```

The installer checks Kind port `19100` before starting the relay, discovers the
current control-plane IP, and applies the ServiceMonitor, alerts, and Kali Sentinel dashboards.
It refuses a relay-port conflict and leaves existing containers and volumes
untouched. Existing alert rules are backed up in `backups/` before changes.

## Validation

```sh
cd ~/Projects/kali-command-center
(cd socket-monitoring && python3 -m unittest discover -s tests -v)
python3 -m py_compile socket-monitoring/exporter/socket_inventory_exporter.py
systemctl --user status kali-socket-inventory-exporter kali-socket-inventory-relay --no-pager
curl -fsS http://172.22.0.2:19100/metrics | grep -E '^kali_socket_inventory_(scrape_success|process_metadata_available|sockets)'
curl -fsSG http://127.0.0.1:19090/api/v1/targets | python3 -m json.tool
curl -fsSG http://127.0.0.1:19090/api/v1/query --data-urlencode 'query=kali_socket_inventory_process_metadata_available'
kubectl get servicemonitor kali-socket-inventory -n default
kubectl get prometheusrule kali-command-center -n default
```

## Metric semantics

- `kali_socket_inventory_last_seen_timestamp_seconds{...}`: one current row per
  process/socket owner; `availability="available"` means present in the latest
  successful snapshot. Fields include protocol, state, local and peer IP/port,
  process/PID, interface, exposure, app/container and URL.
- `kali_socket_inventory_sockets{protocol,socket_state}`: unique socket
  endpoints; use `tcp` + `LISTEN` for TCP listener counts. UDP is typically
  `UNCONN`, since UDP has no TCP-style listen state.
- `kali_socket_listener_change{change="new|disappeared",...}` and its timestamp
  retain transition events for 15 minutes, keyed by protocol, local port, and bind
  address so changing a service from loopback to wildcard is detected. A one-time
  baseline reset occurred when upgrading from the older port-only identity model;
  its prior state is backed up locally. The first snapshot after a schema change
  establishes a fresh baseline;
  it does not call every existing port “new”. A failed or truncated sample does
  not update the baseline. State is stored locally with restrictive permissions.
- `kali_socket_listener_expected_up{...}` tracks configured critical listeners;
  edit `expected_listeners` in `config.json` to match your environment.
- Tune alert severity and pending durations in `alerts/kali-command-center-rules.yaml`;
  listener expectations are configured in `config.json`. Changes are applied by
  `scripts/deploy-user.sh` after a local backup of the current Kubernetes rule.
- `kali_socket_inventory_scrape_success`, `...process_metadata_available`,
  `...baseline_initialized`, and `...truncated` describe evidence quality.
- HTTP(S) health checks run HEAD only against the verified URL allowlist, do
  not follow redirects, and retain standard TLS certificate validation.
  `kali_socket_inventory_application_health` is 1 when the endpoint returns
  any HTTP response and 0 when connection/TLS fails; its `status_code` label
  contains the HTTP response and `..._status_code` is zero when no response arrived. The KPI also counts
  registered `kali_cc_health_check_up` checks. A missing series means no checks
  were registered; it is not evidence of zero failures.
- Prometheus stores historical trends subject to the cluster's configured
  retention. Inventory labels include process/PID/address, so review retention
  and cardinality before increasing the row cap.

## URL and exposure rules

Only URLs in `config.json`'s `ports` allowlist become clickable. Unknown ports
are not assumed to be web services. `wildcard` means bound to `0.0.0.0`, `::`,
or `*`; this signals a reachability review, not proof that an external firewall
allows access. Private, public, loopback, link-local, and unknown are based on
the local bind address. For interfaces, the exporter maps local host addresses
using `ip -j address`; wildcard binds are classified as interface `all`.

## Troubleshooting

- Exporter: `journalctl --user -u kali-socket-inventory-exporter -n 100 --no-pager`
- Relay: `journalctl --user -u kali-socket-inventory-relay -n 100 --no-pager`
- Confirm Kind: `docker ps --filter name=devsecops-control-plane`
- Confirm node listener: `docker exec devsecops-control-plane ss -ltn | grep 19100`
- Confirm target: open Prometheus Targets at <http://localhost:19090/targets> and
  check `kali-socket-inventory` health/error details.
- If target is absent, confirm ServiceMonitor label `release=monitoring`,
  Endpoints address matches the current Kind node IP, and Prometheus selects
  ServiceMonitors in `default`.
- If metrics show `scrape_success=0`, inspect exporter logs and ensure
  `/usr/bin/ss` is installed. If process metadata is `0`, run the reviewed
  `scripts/install.sh` or keep the documented unavailable state.
- Dashboard: <http://localhost:13000/dashboards>. Grafana dashboard is provisioned
  from `dashboards/kali-sentinel/kali-sentinel-sockets.json` using the existing
  Kali Sentinel dashboard ConfigMap provisioner. The catalog companion is
  provisioned from `dashboards/kali-sentinel/linux-network-stack-node-exporter.json`. The executive overview and file integrity coverage dashboard are provisioned from `dashboards/kali-sentinel/kali-sentinel-overview.json` and `dashboards/kali-sentinel/kali-sentinel-file-integrity.json`.
