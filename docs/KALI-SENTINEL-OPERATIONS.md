# Kali Sentinel operations and rollback

## Quick status

```bash
kubectl --context kind-devsecops -n default get pods -o wide
kubectl --context kind-devsecops -n default get servicemonitor dbcc-dam-metrics
systemctl --user status dbcc-mariadb-audit-collector dbcc-metrics-unix-proxy dbcc-metrics-socket-relay
curl -fsS http://127.0.0.1:18765/api/health
curl -fsS http://127.0.0.1:18765/api/dam/coverage
curl -fsSG http://127.0.0.1:19090/api/v1/query --data-urlencode 'query=up{job="dbcc-dam-metrics"}'
curl -fsSG http://127.0.0.1:19090/api/v1/query --data-urlencode 'query=dbcc_dam_events_stored{job="dbcc-dam-metrics"}'
```

Use the [Audit & Monitoring Health](http://localhost:13000/d/kali-sentinel-audit-health/audit-monitoring-health) dashboard. A healthy DBCC scrape means the endpoint responds; the collector heartbeat does not independently prove MariaDB audit settings or event completeness.

## MariaDB audit state

The live server currently has `SERVER_AUDIT` active with logging on, `CONNECT,QUERY,TABLE` events, and SYSLOG output identified as `dbcc_mariadb_audit`. Full SQL text remains in the host journal. DBCC redacts literals/comments in the normalized SQLite copy only.

Check state in an authenticated MariaDB session:

```sql
SHOW GLOBAL VARIABLES
WHERE Variable_name IN (
  'server_audit_logging',
  'server_audit_events',
  'server_audit_output_type',
  'server_audit_syslog_ident'
);
```

The intended persistent file is `../enterprise-database-command-center/deploy/mariadb/99-dbcc-audit.cnf`. Install and restart with an administrator account during a suitable maintenance window:

```bash
sudo install -o root -g root -m 0644 \
  ../enterprise-database-command-center/deploy/mariadb/99-dbcc-audit.cnf \
  /etc/mysql/mariadb.conf.d/99-dbcc-audit.cnf
sudo systemctl restart mariadb
```

Then repeat the SQL check and confirm a new harmless statement is visible in DBCC coverage. Do not print raw journal records into tickets or dashboards; those records can contain sensitive SQL text.

## Reprovision dashboards

From the Kali Command Center repository, with the intended context selected:

```bash
./deploy/apply-kali-sentinel-dashboards.sh
```

The script updates only ConfigMaps named `kali-sentinel-*` and labels them for the existing Grafana dashboard sidecar.

## Privileged and file integrity coverage

Before adding audit rules, inspect existing rules and Wazuh scope with an administrator:

```bash
sudo auditctl -s
sudo auditctl -l
sudo grep -RniE '^[[:space:]]*(<localfile>|<directories>|<ignore>)' /var/ossec/etc 2>/dev/null
```

Do not add duplicate watches until current rules, path exclusions, audit backlog limits, and Wazuh forwarding are understood. Keep detailed audit records in restricted log storage, not Prometheus labels.

## Storage and log pipeline

```bash
df -h / /mnt/vmstorage /mnt/elements
journalctl --disk-usage
kubectl --context kind-devsecops -n default get prometheus monitoring-kube-prometheus-prometheus -o yaml
```

Do not deploy Loki/Alloy until an ext4 storage target, ingestion estimate, retention bound, and free-space reserve have been selected. `/mnt/vmstorage` was already close to full during discovery.

## Rollback

- **Dashboard changes:** delete only the `kali-sentinel-*` ConfigMaps in the chosen namespace. The Grafana sidecar removes those provisioned dashboards. Keep existing dashboards and other ConfigMaps.
- **DBCC relay:** `systemctl --user stop dbcc-metrics-socket-relay dbcc-metrics-unix-proxy`; restore the previous unit files and Service endpoint if needed. This stops only the DBCC metrics path.
- **MariaDB audit:** remove `/etc/mysql/mariadb.conf.d/99-dbcc-audit.cnf` and restart MariaDB to return to the prior persisted settings. Runtime changes can also be reverted in a privileged MariaDB session. Preserve journal and DBCC evidence.
- **Alert:** remove `KaliSentinelDBCCCollectorHeartbeatStale` from `alerts/kali-command-center-rules.yaml` and reapply that PrometheusRule if it causes problems.
- **Data safety:** do not delete database files, audit logs, container volumes, or backups as part of rollback.
