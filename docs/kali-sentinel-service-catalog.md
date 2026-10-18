# Kali Sentinel service catalog

Discovery date: 2026-10-18. Listener bindings are not proof of firewall reachability. HTTPS trust was not verified. Port-forward routes require their forwarding processes.

| Service ID | Application | Runtime / listener | Verified browser URL | Health evidence | Authentication / exposure |
|---|---|---|---|---|---|
| grafana | Grafana 13.1.0 | Kubernetes / HTTP localhost:13000 | http://localhost:13000/ | /api/health HTTP 200 | Login; port-forward |
| prometheus | Prometheus 3.12.0 | Kubernetes / HTTP localhost:19090 | http://localhost:19090/graph | API responds; DBCC target up | Local port-forward |
| kubernetes-dashboard | Kubernetes Dashboard | Kubernetes / HTTPS localhost:8443 | https://localhost:8443/ | HTTP 200; TLS unverified | Token; port-forward |
| dbcc | DBCC Uvicorn application | Host / HTTP 127.0.0.1:18765 | http://127.0.0.1:18765/ | /api/health HTTP 200 | Local app auth |
| dbcc-relay | DBCC Prometheus relay | Docker in Kind node netns / TCP 172.22.0.2:18766 | No web UI discovered | Prometheus target UP | Cluster internal; no host port |
| mariadb | MariaDB 11.8.8 | Host / MySQL 0.0.0.0:3306 | No web UI discovered | Active; audit ON at runtime; not persistent | DB account; wildcard bind |
| mythic-postgres | PostgreSQL-compatible Mythic DB | Docker / TCP 127.0.0.1:5432 | No web UI discovered | Container healthy | Database auth; loopback |
| hackafrica-redis | Redis 7 | Docker / TCP 0.0.0.0:6381 | No web UI discovered | PING PONG; healthy | Auth unverified; wildcard |
| mythic-rabbitmq | Mythic RabbitMQ | Docker / AMQP 127.0.0.1:5672 | No web UI discovered | Container healthy | AMQP auth; loopback |
| dbcc-sqlite | DBCC SQLite metadata | Local file ~/.local/share/enterprise-database-command-center/metadata.sqlite3 | No web UI discovered | DBCC responds | Local file |
| portainer | Portainer CE | Docker / HTTPS 0.0.0.0:9443 | https://localhost:9443/ | HTTP 200; TLS unverified | Login; wildcard bind |
| netdata | Netdata 2.11 nightly | Host / HTTP 0.0.0.0:19999 | http://localhost:19999/ | HTTP 200 | Auth unverified; wildcard |
| falco | Falco | Kubernetes DaemonSet | No web UI discovered | Pod running; metrics scraped | Cluster internal |
| trivy-operator | Trivy Operator | Kubernetes workload | No web UI discovered | Running; vulnerability metrics | Cluster internal |
| floci-ui | Floci UI | Docker / HTTP 0.0.0.0:4500 | http://localhost:4500/ | HTTP 200 | Wildcard bind |
| floci-local-api | Floci local cloud API | Docker / TCP 0.0.0.0:4566 | No web UI discovered | Container healthy; root XML; routes unverified | Wildcard bind |
| floci-proxy | Floci proxy | Docker / TCP 0.0.0.0:4567 | No web UI discovered | Root returns XML | Wildcard bind |
| floci-azure | Floci Azure emulator | Docker / TCP 0.0.0.0:4577 | No web UI discovered | Container healthy; UI unknown | Wildcard bind |
| floci-gcp | Floci GCP emulator | Docker / TCP 0.0.0.0:4588 | No web UI discovered | Container healthy; UI unknown | Wildcard bind |
| mythic-ui | Mythic | Docker / HTTPS 0.0.0.0:7443 | https://localhost:7443/new/login | HTTP 200; self-issued/no-SAN certificate | Login; wildcard |
| mythic-jupyter | Mythic Jupyter | Docker / HTTP 127.0.0.1:8888 | No web UI discovered | Container healthy | Loopback; auth not checked |
| mythic-react | Mythic React | Docker / HTTP 127.0.0.1:3000 | No web UI discovered | Container healthy | Loopback; auth not checked |
| mythic-graphql | Mythic GraphQL | Docker / HTTP 127.0.0.1:8080 | No web UI discovered | Container healthy | Loopback; auth not checked |
| mythic-server | Mythic server | Docker / TCP 127.0.0.1:7000-7010,17443-17444 | No web UI discovered | Container healthy | Loopback |
| mythic-docs | Mythic documentation | Docker / HTTP 127.0.0.1:8090 | No web UI discovered | Container healthy | Loopback |
| mythic-agent-containers | Mythic agent/profile containers | Docker host-network containers | No web UI discovered | Seven containers running; no direct published ports | Host network |
| hackafrica-api | HackAfrica API | Docker internal | No web UI discovered | Restarting; no verified UI | Container internal |
| hackafrica-worker | HackAfrica worker | Docker internal | No web UI discovered | Running | Container internal |
| mailpit | Mailpit | Docker / SMTP 0.0.0.0:1025; HTTP 0.0.0.0:8025 | http://localhost:8025/ | UI HTTP 200; healthy | Wildcard bind |
| kube-api | Kind Kubernetes API | HTTPS localhost:42625 | No web UI discovered | API requires Kubernetes auth | Loopback published port |
| auditd | Linux audit service | Host service | No web UI discovered | Active; rules not verified | Host local |
| wazuh-agent | Wazuh agent | Host service | No web UI discovered | Active; manager/path scope unknown | Host local |
| ssh | OpenSSH | Host / TCP 0.0.0.0:22 | No web UI discovered | Active; firewall unverified | Wildcard bind |
| unbound | Unbound DNS | Host / TCP+UDP 127.0.0.1:53 | No web UI discovered | Active | Loopback |
| listener-443 | Unknown HTTPS listener | Host / TCP *:443 | No web UI discovered | Backend and route unverified | Wildcard bind |
| listener-8081 | Unknown listener | Host / TCP *:8081 | http://localhost:8081/ | HTTP 200 Under Construction; identity unknown | Wildcard bind |
| llmnr | LLMNR-related listener | Host / TCP+UDP *:5355 | No web UI discovered | Listener observed | Wildcard |
| netflow | NetFlow receiver | Host / UDP *:2055,*:6343 | No web UI discovered | Listener observed | Wildcard |
| otel | OpenTelemetry plugin | Host / TCP 127.0.0.1:4317 | No web UI discovered | Listener observed | Loopback |
| teamviewer | TeamViewer | Host / TCP 127.0.0.1:5939 | No web UI discovered | Listener observed | Loopback |
| vmware | Vagrant VMware utility | Host / TCP 127.0.0.1:9922 | No web UI discovered | Listener observed | Loopback |
| containerd | containerd | Host / TCP 127.0.0.1:45373 | No web UI discovered | Listener observed | Loopback |
| vscode | VS Code-related processes | TCP 127.0.0.1:36951,8828; wildcard :47821,:47822 | No web UI discovered | Process association observed | Mixed |
| datadog-agent | Datadog Agent | Docker internal | No web UI discovered | Restarting/unhealthy | Container internal |

## Coverage gaps

- No database performance exporters; connection utilization, latency, replication, and backup freshness are not measured.
- No Loki/Alloy log backend. Host journal uses about 4 GB; /mnt/vmstorage is about 94% full.
- Prometheus retains 10 days on ephemeral storage; no PVC is configured.
- auditd rules and Wazuh server/path coverage remain unverified.
- MariaDB audit is active at runtime but the persistent configuration install is pending.
