# Kali Sentinel socket inventory

Read-only inventory and Prometheus dashboard for the host output of `ss -ltnup`.
It inventories TCP `LISTEN` sockets and UDP sockets, local/peer endpoints, state,
process name/PID (when available), interface, exposure class, Docker published
port identity, a verified application URL allowlist, and last-seen time.

## Live deployment

- Grafana dashboard: <http://localhost:13000/d/kali-sentinel-sockets/kali-sentinel-listening-sockets?orgId=1&from=now-6h&to=now&timezone=browser&refresh=30s>
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
current control-plane IP, and applies the ServiceMonitor, alerts, and dashboards.
It refuses a relay-port conflict and leaves existing containers and volumes
untouched. Existing alert rules are backed up in `backups/` before changes.

## Validation

```sh
cd ~/Projects/kali-command-center
cd socket-monitoring && python3 -m unittest discover -s tests -v
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
  address so changing a service from loopback to wildcard is detected. The first
  run establishes a baseline;
  it does not call every existing port “new”. A failed or truncated sample does
  not update the baseline. State is stored locally with restrictive permissions.
- `kali_socket_listener_expected_up{...}` tracks configured critical listeners;
  edit `expected_listeners` in `config.json` to match your environment.
- `kali_socket_inventory_scrape_success`, `...process_metadata_available`,
  `...baseline_initialized`, and `...truncated` describe evidence quality.
- HTTP(S) health checks run only against the verified URL allowlist, with
  standard TLS certificate validation. `kali_socket_inventory_application_health`
  is 1 when the endpoint returns any HTTP response and 0 when connection/TLS
  fails; `..._status_code` is zero when no response arrived. The KPI also counts
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
  Kali Sentinel dashboard ConfigMap provisioner.
