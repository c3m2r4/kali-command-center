# Kali Sentinel

Kali Sentinel reuses the existing Grafana and Prometheus stack. Dashboards live in `dashboards/kali-sentinel/`, are provisioned into the Grafana folder `07 - Kali Sentinel`, and use actual Prometheus metrics where available. Missing event sources are marked as coverage gaps rather than zero activity.

## Dashboards

- [Executive Overview](http://localhost:13000/d/kali-sentinel-overview/kali-sentinel-executive-overview)
- [Service Catalog & Health](http://localhost:13000/d/kali-sentinel-services/service-catalog-and-health)
- [Database Fleet](http://localhost:13000/d/kali-sentinel-db-fleet/database-fleet)
- [Database Activity Monitoring](http://localhost:13000/d/kali-sentinel-dam/database-activity-monitoring)
- [Privileged Activity](http://localhost:13000/d/kali-sentinel-privileged-audit/privileged-activity)
- [File Integrity](http://localhost:13000/d/kali-sentinel-file-integrity/file-integrity)
- [Application & API Security](http://localhost:13000/d/kali-sentinel-appsec/application-api-security)
- [Audit & Monitoring Health](http://localhost:13000/d/kali-sentinel-audit-health/audit-monitoring-health)

Service metadata is in `config/kali-sentinel-service-catalog.json`; a human-readable inventory is in `docs/kali-sentinel-service-catalog.md`.

## Current coverage

- Prometheus `dbcc-dam-metrics` target is up at the Kind control-plane address. The relay shares the Kind node network namespace and publishes no host port.
- MariaDB `SERVER_AUDIT` is active at runtime with `CONNECT,QUERY,TABLE` events sent to the system journal. A harmless `SELECT 1` was observed and normalized by DBCC. Full statements remain in the host journal; only DBCC's normalized copy redacts literals/comments.
- MariaDB settings are **not persistent yet**. The deployable configuration is `../enterprise-database-command-center/deploy/mariadb/99-dbcc-audit.cnf`. Installing it under `/etc/mysql/mariadb.conf.d/` and restarting MariaDB requires an administrator with sudo.
- Database performance exporters, Loki/Alloy, verified auditd rules, and Wazuh destination/path coverage remain outstanding. Do not infer zero events from those gaps.
- Prometheus storage is ephemeral and `/mnt/vmstorage` is near capacity. Centralized log storage is deferred until a retention/capacity plan is set.

## Reprovision dashboard ConfigMaps

Run `./deploy/apply-kali-sentinel-dashboards.sh` from the Kali Command Center repository with the intended Kubernetes context selected. It creates or updates the dashboard ConfigMaps consumed by the Grafana sidecar.

## Validation completed

- All eight dashboard JSON files parse.
- All 33 PromQL expressions were accepted by Prometheus after substituting Grafana's `$__range` variable with a concrete range for syntax validation.
- Grafana API reports all eight dashboard UIDs in `07 - Kali Sentinel`.
- Prometheus target `dbcc-dam-metrics` reports `up`; the scraped stored-event gauge increased from 23 to 27 during the audit validation.

## Remaining implementation work

Root/sudo audit and file-integrity rules need privileged read-only inspection before any new watches are considered. MariaDB persistent config installation needs sudo and a restart window. Database exporters require reviewed credentials/grants and verified network paths. Loki/Alloy requires a storage target and bounded retention first. These are tracked gaps, not successful controls.
