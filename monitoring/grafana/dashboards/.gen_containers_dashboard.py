#!/usr/bin/env python3
"""Generate the "Beyou — Containers" Grafana dashboard.

The fleet view for the whole stack: every Beyou container's resources
(cAdvisor), scrape-target availability (Prometheus up), host health
(node-exporter), the app DB from the DB's own side (postgres-exporter), and
error/log volume (Loki). Backend JVM internals stay in the consolidated
service-health dashboard, which this one links to.

Run:  python3 .gen_containers_dashboard.py  ->  writes beyou-containers.json
"""
import json
import os

DS = {"type": "prometheus", "uid": "prometheus"}
LOKI_DS = {"type": "loki", "uid": "loki"}

# cAdvisor reports every container on the host; this host runs unrelated
# stacks. Scope to compose projects whose name starts with "beyou" (RE2
# supports (?i), same spirit as the keep rule in monitoring/alloy/config.alloy).
CT = 'container_label_com_docker_compose_project=~"(?i)beyou.*"'
SVC = "container_label_com_docker_compose_service"

# ---------------------------------------------------------------- layout engine
_state = {"x": 0, "y": 0, "row_h": 0, "id": 0}
panels = []


def _next_id():
    _state["id"] += 1
    return _state["id"]


def row(title):
    if _state["x"] > 0:
        _state["y"] += _state["row_h"]
        _state["x"] = 0
        _state["row_h"] = 0
    panels.append({
        "collapsed": False,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": _state["y"]},
        "id": _next_id(),
        "panels": [],
        "title": title,
        "type": "row",
    })
    _state["y"] += 1


def _place(w, h):
    if _state["x"] + w > 24:
        _state["y"] += _state["row_h"]
        _state["x"] = 0
        _state["row_h"] = 0
    pos = {"h": h, "w": w, "x": _state["x"], "y": _state["y"]}
    _state["x"] += w
    _state["row_h"] = max(_state["row_h"], h)
    return pos


def _targets(exprs, ds=DS):
    out = []
    for i, (expr, legend, extra) in enumerate(exprs):
        t = {"datasource": ds, "expr": expr, "refId": chr(ord("A") + i)}
        if legend is not None:
            t["legendFormat"] = legend
        t.update(extra)
        out.append(t)
    return out


def stat(title, desc, exprs, w=5, h=5, unit="short", color="green",
         thresholds=None, graph="none", text_mode="auto", ds=DS):
    steps = thresholds or [{"color": color, "value": None}]
    fc = {"color": {"mode": "thresholds" if thresholds else "fixed",
                    "fixedColor": color}, "mappings": [], "unit": unit,
          "thresholds": {"mode": "absolute", "steps": steps}}
    panels.append({
        "datasource": ds, "description": desc,
        "fieldConfig": {"defaults": fc, "overrides": []},
        "gridPos": _place(w, h), "id": _next_id(),
        "options": {"colorMode": "value", "graphMode": graph,
                    "justifyMode": "auto", "orientation": "auto",
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "",
                                      "values": False},
                    "textMode": text_mode, "wideLayout": True},
        "targets": _targets(exprs, ds=ds),
        "title": title, "type": "stat",
    })


def ts(title, desc, exprs, w=8, h=7, unit="short", stack=False, ds=DS,
       legend_table=True):
    custom = {
        "axisBorderShow": False, "axisCenteredZero": False,
        "axisColorMode": "text", "axisPlacement": "auto", "barAlignment": 0,
        "drawStyle": "line", "fillOpacity": 10, "gradientMode": "none",
        "hideFrom": {"legend": False, "tooltip": False, "viz": False},
        "insertNulls": False, "lineInterpolation": "linear", "lineWidth": 1,
        "pointSize": 5, "scaleDistribution": {"type": "linear"},
        "showPoints": "auto", "spanNulls": False,
        "stacking": {"group": "A", "mode": "normal" if stack else "none"},
        "thresholdsStyle": {"mode": "off"},
    }
    defaults = {"color": {"mode": "palette-classic"}, "custom": custom,
                "mappings": [], "unit": unit,
                "thresholds": {"mode": "absolute",
                               "steps": [{"color": "green", "value": None}]}}
    panels.append({
        "datasource": ds, "description": desc,
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "gridPos": _place(w, h), "id": _next_id(),
        "options": {"legend": {"calcs": [], "displayMode":
                    "table" if legend_table else "list",
                    "placement": "right" if legend_table else "bottom",
                    "showLegend": True},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
        "targets": _targets(exprs, ds=ds), "title": title, "type": "timeseries",
    })


# ================================================================ FLEET
row("Fleet — every container right now")
stat("Containers tracked",
     "Compose services currently reporting to cAdvisor (a stopped container "
     "drops out of this count, which is how you notice one died silently).",
     [(f"count(sum by({SVC})(rate(container_cpu_usage_seconds_total{{{CT}}}[5m])))",
       None, {"instant": True})],
     w=5, h=5, unit="short")
_merge_table = [{"id": "merge", "options": {}},
                {"id": "organize", "options": {
                    "excludeByName": {"Time": True, "__name__": True,
                                      "instance": True, "job": True,
                                      "name": True, "image": True,
                                      "container_label_com_docker_compose_project": True,
                                      "id": True},
                    "renameByName": {
                        SVC: "Service",
                        "Value #A": "CPU (cores)",
                        "Value #B": "Memory",
                        "Value #C": "Mem % of limit",
                        "Value #D": "Net RX",
                        "Value #E": "Net TX",
                        "Value #F": "Uptime"}}}]
panels.append({
    "datasource": DS, "description":
        "One row per running Beyou container, merged from instant queries. "
        "CPU = cores used (5m rate); Memory = working set; Net = eth0 "
        "bytes/s; Uptime resets to zero on every restart.",
    "fieldConfig": {"defaults": {
        "custom": {"align": "auto", "cellOptions": {"type": "auto"},
                   "inspect": False},
        "mappings": [],
        "thresholds": {"mode": "absolute",
                       "steps": [{"color": "green", "value": None}]}},
        "overrides": [
            {"matcher": {"id": "byName", "options": "Uptime"},
             "properties": [{"id": "unit", "value": "s"}]},
            {"matcher": {"id": "byName", "options": "Memory"},
             "properties": [{"id": "unit", "value": "decbytes"}]},
            {"matcher": {"id": "byName", "options": "Mem % of limit"},
             "properties": [{"id": "unit", "value": "percent"},
                            {"id": "max", "value": 100}]},
            {"matcher": {"id": "byName", "options": "Net RX"},
             "properties": [{"id": "unit", "value": "Bps"}]},
            {"matcher": {"id": "byName", "options": "Net TX"},
             "properties": [{"id": "unit", "value": "Bps"}]}]},
    "gridPos": _place(19, 10), "id": _next_id(),
    "options": {"cellHeight": "sm",
                "footer": {"countRows": False, "fields": "",
                           "reducer": ["sum"], "show": False},
                "showHeader": True},
    "pluginVersion": "11.6.0",
    "targets": _targets([
        (f"sum by({SVC})(rate(container_cpu_usage_seconds_total{{{CT}}}[5m]))", None, {"format": "table", "instant": True}),
        (f"sum by({SVC})(container_memory_working_set_bytes{{{CT}}})", None, {"format": "table", "instant": True}),
        (f"100 * sum by({SVC})(container_memory_working_set_bytes{{{CT}}}) / clamp_min(sum by({SVC})(container_spec_memory_limit_bytes{{{CT}}}), 1)", None, {"format": "table", "instant": True}),
        (f"sum by({SVC})(rate(container_network_receive_bytes_total{{{CT},interface=\"eth0\"}}[5m]))", None, {"format": "table", "instant": True}),
        (f"sum by({SVC})(rate(container_network_transmit_bytes_total{{{CT},interface=\"eth0\"}}[5m]))", None, {"format": "table", "instant": True}),
        (f"time() - min by({SVC})(container_start_time_seconds{{{CT}}})", None, {"format": "table", "instant": True}),
    ]),
    "title": "Containers", "type": "table",
    "transformations": _merge_table,
})

# ================================================================ RESOURCES
row("Resources (per container)")
ts("CPU (cores) by service",
   "CPU cores used per service (5m rate of cAdvisor's cumulative counter). "
   "A value of 2.0 = two cores busy. Flat 0 = idle, not dead.",
   [(f"sum by({SVC})(rate(container_cpu_usage_seconds_total{{{CT}}}[5m]))",
     f"{{{{{SVC}}}}}", {})])
ts("Memory working set",
   "Working-set memory per service: the bytes the kernel considers actively "
   "used by the container. This is the number to compare against the limit, "
   "not cAdvisor's raw usage (which includes page cache).",
   [(f"sum by({SVC})(container_memory_working_set_bytes{{{CT}}})",
     f"{{{{{SVC}}}}}", {})],
   unit="decbytes")
ts("Memory % of limit",
   "Working set divided by the container's declared memory limit. Services "
   "without a compose limit (no deploy.resources) show no line, which is "
   "honest: there is no ceiling to measure against.",
   [(f"100 * sum by({SVC})(container_memory_working_set_bytes{{{CT}}}) / clamp_min(sum by({SVC})(container_spec_memory_limit_bytes{{{CT}}}), 1)",
     f"{{{{{SVC}}}}}", {})],
   unit="percent")
ts("Network (eth0) RX / TX",
   "Bytes/s in and out of the container's primary interface. A steady "
   "baseline is normal (SSE, polling); a ramp with no traffic change is "
   "usually a client retrying.",
   [(f"sum by({SVC})(rate(container_network_receive_bytes_total{{{CT},interface=\"eth0\"}}[5m]))",
     f"{{{{{SVC}}}}} RX", {}),
    (f"sum by({SVC})(rate(container_network_transmit_bytes_total{{{CT},interface=\"eth0\"}}[5m]))",
     f"{{{{{SVC}}}}} TX", {})],
   unit="Bps")
ts("Disk used %",
   "Container writable-layer usage against its declared filesystem limit. "
   "Steady growth here is uploads/logs living in the container layer instead "
   "of a volume.",
   [(f"100 * sum by({SVC})(container_fs_usage_bytes{{{CT}}}) / clamp_min(sum by({SVC})(container_fs_limit_bytes{{{CT}}}), 1)",
     f"{{{{{SVC}}}}}", {})],
   unit="percent")
ts("Uptime (resets = restart)",
   "Seconds since the container started. Every sawtooth back to zero is a "
   "restart, so a crash-looping service reads as a comb.",
   [(f"time() - min by({SVC})(container_start_time_seconds{{{CT}}})",
     f"{{{{{SVC}}}}}", {})],
   unit="s")

# ================================================================ ENDPOINTS
row("Endpoints (Prometheus scrape targets)")
stat("Scrape targets (1 = answering)",
     "up{job=...} for every job in prometheus.yml. 1 = the target answered "
     "its last scrape; 0 = down or unreachable. watchtower is absent in dev "
     "by design. This is scrape-level availability; deep health per service "
     "lives in GlitchTip's Uptime page.",
     [(f"up{{job=\"{job}\"}}", "{{job}}", {"instant": True})
      for job in [
          "beyou-backend", "glitchtip", "loki", "alloy",
          "prometheus", "cadvisor", "node-exporter", "postgres-exporter",
          "grafana", "watchtower",
      ]],
     w=24, h=5, unit="short",
     thresholds=[{"color": "red", "value": None},
                 {"color": "green", "value": 1}],
     text_mode="value_and_name")

# ================================================================ HOST
row("Host (node-exporter)")
ts("CPU usage",
   "Host CPU busy share (idle subtracted). A sustained 100% here with low "
   "container CPU in the Resources row = something on the host outside "
   "Docker (backup, scan, another stack).",
   [(f"100 - avg by(instance)(rate(node_cpu_seconds_total{{mode=\"idle\"}}[5m])) * 100",
     "{{instance}}", {})],
   unit="percent")
ts("Load average",
   "Run-queue length 1/5/15m. Above the CPU count (node_cpu_seconds_total "
   "does not tell you that; the dashboard's system_cpu_count in the "
   "service-health board does) = threads waiting for CPU.",
   [(f"node_load1{{instance=~\"$instance\"}}", "load1", {}),
    (f"node_load5{{instance=~\"$instance\"}}", "load5", {}),
    (f"node_load15{{instance=~\"$instance\"}}", "load15", {})])
ts("Memory used",
   "Host memory in use = total minus MemAvailable (the kernel's own "
   "available estimate, which accounts for reclaimable cache).",
   [(f"(node_memory_MemTotal_bytes{{instance=~\"$instance\"}} - node_memory_MemAvailable_bytes{{instance=~\"$instance\"}}) / node_memory_MemTotal_bytes{{instance=~\"$instance\"}} * 100",
     "{{instance}}", {})],
   unit="percent")
ts("Root disk used",
   "Host root filesystem usage. This is the disk that holds docker volumes, "
   "so it is the one that fills when logs or the Loki store grow.",
   [(f"100 - 100 * node_filesystem_avail_bytes{{mountpoint=\"/\",fstype!~\"tmpfs|overlay\"}} / node_filesystem_size_bytes{{mountpoint=\"/\",fstype!~\"tmpfs|overlay\"}}",
     "{{instance}} /", {})],
   unit="percent")
ts("Network (host)",
   "Host physical interfaces RX/TX. Contrast with per-container Network "
   "above: the difference is traffic between containers, which never leaves "
   "the host.",
   [(f"rate(node_network_receive_bytes_total{{device=~\"eth.*|enp.*|ens.*\"}}[5m])", "{{device}} RX", {}),
    (f"rate(node_network_transmit_bytes_total{{device=~\"eth.*|enp.*|ens.*\"}}[5m])", "{{device}} TX", {})],
   unit="Bps")
stat("Host uptime",
     "Seconds since the host booted. A drop means the whole box restarted, "
     "which explains every container restarting at once.",
     [("time() - node_boot_time_seconds", None, {"instant": True})],
     w=5, h=5, unit="s")

# ================================================================ POSTGRES
row("Postgres (app DB, from the DB's own side)")
stat("Postgres up",
     "pg_up: 1 = the exporter holds a live connection to the database. The "
     "dashboard's DB liveness signal, independent of the backend's pool.",
     [("pg_up", None, {"instant": True})],
     w=4, h=5, unit="short",
     thresholds=[{"color": "red", "value": None},
                 {"color": "green", "value": 1}],
     text_mode="value_and_name")
stat("Connections",
     "Backend processes (pg_stat_activity rows) summed over all databases, "
     "including the exporter's own. Compare with the backend's HikariCP "
     "panels: pool exhaustion shows here as a plateau at max_connections.",
     [("sum(pg_stat_database_numbackends)", None, {"instant": True})],
     w=4, h=5, unit="short")
stat("DB size",
     "Total on-disk size of every database, summed.",
     [("sum(pg_database_size_bytes)", None, {"instant": True})],
     w=4, h=5, unit="decbytes")
ts("Connections by database",
   "Backend processes per database. A second, flatter line is the exporter "
   "itself; a spike here with low HTTP traffic is a connection leak or a "
   "long-running query.",
   [(f"sum by(datname)(pg_stat_database_numbackends)", "{{datname}}", {})],
   w=12)
ts("Cache hit ratio",
   "Shared-buffer hits / (hits + reads) over 5m. Above 0.99 is healthy for "
   "an app DB; sustained dips below 0.95 mean the working set outgrew "
   "shared_buffers or cold-cache churn.",
   [("sum(rate(pg_stat_database_blks_hit[5m])) / (sum(rate(pg_stat_database_blks_hit[5m])) + sum(rate(pg_stat_database_blks_read[5m])))",
     "hit ratio", {})],
   w=12, unit="percentunit")
ts("Commits vs rollbacks",
   "Transaction commit and rollback rates. A rollback rate climbing toward "
   "commits means application code is erroring mid-transaction.",
   [("sum(rate(pg_stat_database_xact_commit[5m]))", "commits/s", {}),
    ("sum(rate(pg_stat_database_xact_rollback[5m]))", "rollbacks/s", {})],
   unit="ops")
ts("Deadlocks",
   "Deadlock counter rate per database. Any non-zero sustained rate is a "
   "bug in lock ordering, not noise.",
   [("sum by(datname)(rate(pg_stat_database_deadlocks[5m]))", "{{datname}}", {})],
   unit="ops")
ts("Locks held",
   "Active locks by database (all modes). A persistent wall at one database "
   "means that DB is the contention point; the lock mode labels in Explore "
   "tell you which kind.",
   [("sum by(datname)(pg_locks)", "{{datname}}", {})])

# ================================================================ LOGS
row("Logs (Loki)")
stat("Services with errors (5m)",
     "Number of Beyou services that emitted at least one line detected as "
     "error in the last 5 minutes. 0 is the resting state; when it climbs, "
     "the panel below says which service.",
     [(f"count(count by(service)(count_over_time({{project=~\"(?i)beyou.*\"}} | detected_level=\"error\" [5m])))",
       None, {"instant": True})],
     w=6, h=5, unit="short", ds=LOKI_DS)
ts("Log volume by service",
   "Lines per 5m window per service, from Loki's index (volume_enabled). "
   "This is where a log flood becomes visible as a wall before anything "
   "alerts.",
   [(f"sum by(service)(count_over_time({{project=~\"(?i)beyou.*\"}} [5m]))",
     "{{service}}", {})],
   w=9, ds=LOKI_DS)
ts("Error lines by service",
   "Rate of lines Loki detected as error level, per service. Click a "
   "service in the legend, then Explore, to read the actual lines.",
   [(f"sum by(service)(rate({{project=~\"(?i)beyou.*\"}} | detected_level=\"error\" [5m]))",
     "{{service}}", {})],
   w=9, unit="ops", ds=LOKI_DS)

# ================================================================ DASHBOARD
dashboard = {
    "annotations": {"list": [{
        "builtIn": 1, "enable": True, "hide": True,
        "iconColor": "rgba(0, 211, 255, 1)",
        "name": "Annotations & Alerts", "type": "dashboard"}]},
    "description": "Fleet health for every Beyou container: resources "
                   "(cAdvisor), scrape targets (Prometheus up), host "
                   "(node-exporter), the app DB from the DB's own side "
                   "(postgres-exporter) and log/error volume (Loki). Backend "
                   "JVM internals live in the consolidated service-health "
                   "dashboard, linked below.",
    "editable": True, "fiscalYearStartMonth": 0, "graphTooltip": 1,
    "links": [
        {"title": "Backend JVM deep dive", "url": "/d/beyou-service-health",
         "targetBlank": False},
        {"title": "Beyou Logs", "url": "/d/beyou-logs", "targetBlank": False},
        {"title": "Beyou AI Agent", "url": "/d/beyou-ai-agent",
         "targetBlank": False},
    ],
    "panels": panels, "refresh": "30s", "schemaVersion": 39,
    "tags": ["beyou", "containers", "fleet"],
    "templating": {"list": [{
        "current": {"text": "All", "value": "$__all"},
        "datasource": DS,
        "definition": "label_values(instance)",
        "includeAll": True, "label": "Instance", "multi": True,
        "name": "instance", "options": [],
        "query": {"query": "label_values(instance)", "refId": "A"},
        "refresh": 2, "sort": 1, "type": "query"}]},
    "time": {"from": "now-6h", "to": "now"}, "timepicker": {},
    "timezone": "browser",
    "title": "Beyou — Containers",
    "uid": "beyou-containers",
}

out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "beyou-containers.json")
with open(out, "w") as f:
    json.dump(dashboard, f, indent=2)
    f.write("\n")
print(f"wrote {out}: {len(panels)} panels "
      f"({sum(1 for p in panels if p['type'] == 'row')} rows)")
