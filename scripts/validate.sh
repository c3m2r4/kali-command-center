#!/usr/bin/env bash
# Smoke checks for the active local monitoring stack; read-only except for HTTP queries.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
printf '%s\n' '== Local service health =='
curl -fsS http://127.0.0.1:13000/api/health
curl -fsS http://127.0.0.1:19090/-/healthy
printf '\n%s\n' '== Prometheus target health =='
curl -fsSG http://127.0.0.1:19090/api/v1/query --data-urlencode 'query=sum(up)' | python -c 'import json,sys;d=json.load(sys.stdin);print("up targets="+str(d["data"]["result"][0]["value"][1]))'
printf '\n%s\n' '== Command Center data availability =='
for q in kali_cc_exporter_ready kali_cc_metrics_snapshot_timestamp_seconds kali_cc_netdata_scrape_success kali_cc_project_info kali_cc_project_state docker_container_info netdata_system_cpu_percentage_average; do
  printf '%s: ' "$q"
  curl -fsSG http://127.0.0.1:19090/api/v1/query --data-urlencode "query=$q" | python -c 'import json,sys;d=json.load(sys.stdin);print("series="+str(len(d.get("data",{}).get("result",[]))))'
done
printf '%s\n' '== User service state =='
systemctl --user is-active docker-container-exporter.service kali-grafana-forward.service kali-prometheus-forward.service kali-dashboard-forward.service
printf '%s\n' '== Dashboard JSON syntax =='
python - "$repo/dashboards" <<'PY'
import glob,json,os,sys
files=glob.glob(os.path.join(sys.argv[1],'*.json'))
for path in files: json.load(open(path))
print(f'{len(files)} valid dashboard JSON files')
PY
printf '%s\n' '== Prometheus rules =='
kubectl -n default get prometheusrule kali-command-center
