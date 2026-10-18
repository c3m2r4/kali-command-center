#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
state_dir="$HOME/.local/share/kali-socket-inventory"
unit_dir="$HOME/.config/systemd/user"
backup_dir="$state_dir/backups"
mkdir -p "$backup_dir" "$unit_dir"
chmod 700 "$state_dir" "$backup_dir"
for unit in "$repo_dir/socket-monitoring/systemd/user/"*.service; do
  target="$unit_dir/$(basename "$unit")"
  if [[ -e "$target" ]] && ! cmp -s "$unit" "$target"; then
    cp -a "$target" "$backup_dir/$(basename "$target").$(date +%Y%m%d%H%M%S).bak"
  fi
  cp "$unit" "$target"
done
systemctl --user daemon-reload
systemctl --user enable kali-socket-inventory-exporter.service
systemctl --user restart kali-socket-inventory-exporter.service
# Start only if the expected kind control-plane container exists and relay port is not occupied.
if docker inspect devsecops-control-plane >/dev/null 2>&1; then
  if docker inspect kali-socket-inventory-relay >/dev/null 2>&1; then
    relay_network="$(docker inspect kali-socket-inventory-relay --format '{{.HostConfig.NetworkMode}}')"
    if [[ "$relay_network" != container:devsecops-control-plane && "$relay_network" != container:"$(docker inspect devsecops-control-plane --format '{{.Id}}')" ]]; then
      echo 'A container named kali-socket-inventory-relay uses an unexpected network; refusing to replace it.' >&2
      exit 1
    fi
    systemctl --user enable kali-socket-inventory-relay.service
  else
    if docker exec devsecops-control-plane sh -c 'ss -H -ltn 2>/dev/null | grep -q ":19100 "' ; then
      echo 'Kind node port 19100 is already occupied by another process; refusing to start relay.' >&2
      exit 1
    fi
    systemctl --user enable kali-socket-inventory-relay.service
  fi
  # Recreate the relay after exporter restarts so the bind-mounted Unix socket is current.
  systemctl --user restart kali-socket-inventory-relay.service
  node_ip="$(docker inspect devsecops-control-plane --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')"
  test -n "$node_ip"
else
  echo 'Kind control-plane container not found; exporter runs locally, Prometheus scrape integration skipped.' >&2
fi
stamp="$(date +%Y%m%d%H%M%S)"
backup_resource() {
  local resource="$1" name="$2" namespace="${3:-default}" out="$backup_dir/${1//\//_}-${2}-${stamp}.yaml"
  if kubectl -n "$namespace" get "$resource" "$name" -o yaml > "$out" 2>/dev/null; then
    test -s "$out" || rm -f "$out"
  else
    rm -f "$out"
  fi
}
backup_resource service kali-socket-inventory
backup_resource endpoints kali-socket-inventory
backup_resource servicemonitors.monitoring.coreos.com kali-socket-inventory
backup_resource prometheusrules.monitoring.coreos.com kali-command-center
backup_resource configmap kali-sentinel-sockets
if docker inspect devsecops-control-plane >/dev/null 2>&1; then
  node_ip="$(docker inspect devsecops-control-plane --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')"
  test -n "$node_ip"
  sed "s/__KIND_NODE_IP__/$node_ip/g" "$repo_dir/socket-monitoring/kubernetes/servicemonitor.yaml" | kubectl apply -f -
fi
kubectl apply -f "$repo_dir/alerts/kali-command-center-rules.yaml"
kubectl -n default create configmap kali-sentinel-sockets --from-file=kali-sentinel-sockets.json="$repo_dir/dashboards/kali-sentinel/kali-sentinel-sockets.json" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n default label configmap kali-sentinel-sockets grafana_dashboard=1 --overwrite
kubectl -n default annotate configmap kali-sentinel-sockets grafana_folder='07 - Kali Sentinel' --overwrite
echo 'Deployment applied. Check scrape target and metadata status in Grafana.'
