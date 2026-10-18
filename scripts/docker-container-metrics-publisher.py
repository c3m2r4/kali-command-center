#!/usr/bin/python3
"""Publish Docker inventory/stats to a read-only node-exporter textfile ConfigMap."""
import importlib.util
import os
import re
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request

MODULE_PATH = "/home/camara/.local/bin/docker-container-exporter.py"
PROJECT_MODULE_PATH = "/home/camara/Projects/kali-command-center/scripts/project-health-exporter.py"
NAMESPACE = "default"
CONFIGMAP = "docker-host-container-metrics"
INTERVAL = 60

spec = importlib.util.spec_from_file_location("docker_exporter", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
project_spec = importlib.util.spec_from_file_location("project_health_exporter", PROJECT_MODULE_PATH)
project_module = importlib.util.module_from_spec(project_spec)
project_spec.loader.exec_module(project_module)

while True:
    try:
        metrics = module.collect()
        project_metrics = project_module.collect().decode("utf-8")
        metrics += "\n# HELP kali_cc_exporter_ready Project metrics snapshot is available.\n# TYPE kali_cc_exporter_ready gauge\nkali_cc_exporter_ready 1\nkali_cc_metrics_snapshot_timestamp_seconds " + str(time.time()) + "\n" + project_metrics
        netdata_params = urllib.parse.urlencode({"format": "prometheus", "help": "no", "types": "no", "filter": "system.* disk.* disk_space.* disk_inodes.* net.* sensors.*"})
        netdata_url = "http://127.0.0.1:19999/api/v1/allmetrics?" + netdata_params
        try:
            with urllib.request.urlopen(netdata_url, timeout=5) as response:
                netdata_metrics = response.read().decode("utf-8")
            # node-exporter textfile collector rejects client-side sample timestamps.
            netdata_metrics = re.sub(r"(?m)\s+\d{13}$", "", netdata_metrics)
            metrics += "\n# HELP kali_cc_netdata_scrape_success Host Netdata request to loopback succeeded.\n# TYPE kali_cc_netdata_scrape_success gauge\nkali_cc_netdata_scrape_success 1\n# HELP kali_cc_netdata_last_success_timestamp_seconds Last successful local Netdata fetch.\n# TYPE kali_cc_netdata_last_success_timestamp_seconds gauge\nkali_cc_netdata_last_success_timestamp_seconds " + str(time.time()) + "\n" + netdata_metrics
        except Exception:
            metrics += "\n# HELP kali_cc_netdata_scrape_success Host Netdata request to loopback succeeded.\n# TYPE kali_cc_netdata_scrape_success gauge\nkali_cc_netdata_scrape_success 0\n# HELP kali_cc_netdata_last_success_timestamp_seconds Last successful local Netdata fetch.\n# TYPE kali_cc_netdata_last_success_timestamp_seconds gauge\nkali_cc_netdata_last_success_timestamp_seconds 0\n"
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".prom", delete=False) as f:
            f.write(metrics)
            metrics_path = f.name
        try:
            manifest = subprocess.run(
                ["/usr/bin/kubectl", "create", "configmap", CONFIGMAP, "-n", NAMESPACE,
                 "--from-file=metrics.prom=" + metrics_path, "--dry-run=client", "-o", "yaml"],
                check=True, capture_output=True, text=True, timeout=20,
            ).stdout
            subprocess.run(["/usr/bin/kubectl", "apply", "-f", "-"], input=manifest,
                           check=True, capture_output=True, text=True, timeout=20)
        finally:
            os.unlink(metrics_path)
    except Exception as exc:
        print("Docker metrics publish failed: " + str(exc), flush=True)
    time.sleep(INTERVAL)
