#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
dashboard_dir="$repo_dir/dashboards/kali-sentinel"
namespace="${KALI_SENTINEL_NAMESPACE:-default}"

for file in "$dashboard_dir"/*.json; do
  name="$(basename "$file" .json)"
  kubectl -n "$namespace" create configmap "$name" \
    --from-file="$name.json=$file" --dry-run=client -o yaml \
    | kubectl apply -f -
  kubectl -n "$namespace" label configmap "$name" grafana_dashboard=1 --overwrite
  kubectl -n "$namespace" annotate configmap "$name" grafana_folder='07 - Kali Sentinel' --overwrite
done
