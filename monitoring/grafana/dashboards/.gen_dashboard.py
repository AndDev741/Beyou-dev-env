#!/usr/bin/env python3
"""Generate the consolidated Beyou service-health Grafana dashboard.

Targets the REAL metrics exposed by beyou-backend via /actuator/prometheus
(standard Micrometer names, scraped by Prometheus datasource uid="prometheus").
Run:  python3 .gen_dashboard.py  ->  writes beyou-service-health.json
"""
import json
import os

DS = {"type": "prometheus", "uid": "prometheus"}
APP = 'application=~"$application"'  # template variable, defaults to All

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


def _targets(exprs):
    out = []
    for i, (expr, legend, extra) in enumerate(exprs):
        t = {"datasource": DS, "expr": expr, "refId": chr(ord("A") + i)}
        if legend is not None:
            t["legendFormat"] = legend
        t.update(extra)
        out.append(t)
    return out


def stat(title, desc, exprs, w=5, h=5, unit="short", color="green",
         decimals=None, graph="none", text_mode="auto"):
    fc = {"color": {"mode": "fixed", "fixedColor": color}, "mappings": [],
          "unit": unit,
          "thresholds": {"mode": "absolute",
                         "steps": [{"color": color, "value": None}]}}
    if decimals is not None:
        fc["decimals"] = decimals
    panels.append({
        "datasource": DS, "description": desc,
        "fieldConfig": {"defaults": fc, "overrides": []},
        "gridPos": _place(w, h), "id": _next_id(),
        "options": {"colorMode": "value", "graphMode": graph,
                    "justifyMode": "auto", "orientation": "auto",
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "",
                                      "values": False},
                    "textMode": text_mode, "wideLayout": True},
        "targets": _targets([(e, l, x) for (e, l, x) in exprs]),
        "title": title, "type": "stat",
    })


def gauge(title, desc, exprs, w=6, h=8, unit="percentunit", thresholds=None):
    steps = thresholds or [{"color": "red", "value": None},
                           {"color": "yellow", "value": 0.5},
                           {"color": "green", "value": 0.8}]
    panels.append({
        "datasource": DS, "description": desc,
        "fieldConfig": {"defaults": {
            "color": {"mode": "thresholds"}, "mappings": [], "unit": unit,
            "min": 0, "max": 1,
            "thresholds": {"mode": "absolute", "steps": steps}}, "overrides": []},
        "gridPos": _place(w, h), "id": _next_id(),
        "options": {"orientation": "auto", "showThresholdLabels": False,
                    "showThresholdMarkers": True,
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "",
                                      "values": False}},
        "targets": _targets(exprs), "title": title, "type": "gauge",
    })


def ts(title, desc, exprs, w=8, h=7, unit="short", stack=False,
       fill=10, legend_table=True, decimals=None):
    custom = {
        "axisBorderShow": False, "axisCenteredZero": False,
        "axisColorMode": "text", "axisPlacement": "auto", "barAlignment": 0,
        "drawStyle": "line", "fillOpacity": fill, "gradientMode": "none",
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
    if decimals is not None:
        defaults["decimals"] = decimals
    panels.append({
        "datasource": DS, "description": desc,
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "gridPos": _place(w, h), "id": _next_id(),
        "options": {"legend": {"calcs": [], "displayMode":
                    "table" if legend_table else "list",
                    "placement": "right" if legend_table else "bottom",
                    "showLegend": True},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
        "targets": _targets(exprs), "title": title, "type": "timeseries",
    })


def bargauge(title, desc, expr, w=12, h=10, unit="short"):
    panels.append({
        "datasource": DS, "description": desc,
        "fieldConfig": {"defaults": {
            "color": {"mode": "continuous-GrYlRd"}, "decimals": 0,
            "mappings": [], "unit": unit,
            "thresholds": {"mode": "absolute",
                           "steps": [{"color": "green", "value": None}]}},
            "overrides": []},
        "gridPos": _place(w, h), "id": _next_id(),
        "options": {"displayMode": "gradient",
                    "legend": {"calcs": [], "displayMode": "list",
                               "placement": "bottom", "showLegend": False},
                    "maxVizHeight": 300, "minVizHeight": 16, "minVizWidth": 8,
                    "namePlacement": "auto", "orientation": "horizontal",
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "",
                                      "values": False},
                    "showUnfilled": True, "sizing": "auto",
                    "valueMode": "color"},
        "targets": _targets([(expr, "{{__name__}}", {"instant": True})]),
        "title": title, "type": "bargauge",
    })


def table(title, desc, expr, w=12, h=10, exclude=None):
    exclude = exclude or {"Time": True, "__name__": True, "instance": True,
                          "job": True, "application": True}
    panels.append({
        "datasource": DS, "description": desc,
        "fieldConfig": {"defaults": {
            "custom": {"align": "auto", "cellOptions": {"type": "auto"},
                       "inspect": False}, "mappings": [],
            "thresholds": {"mode": "absolute",
                           "steps": [{"color": "green", "value": None}]}},
            "overrides": []},
        "gridPos": _place(w, h), "id": _next_id(),
        "options": {"cellHeight": "sm",
                    "footer": {"countRows": False, "fields": "",
                               "reducer": ["sum"], "show": False},
                    "showHeader": True},
        "pluginVersion": "11.6.0",
        "targets": _targets([(expr, "", {"format": "table", "instant": True})]),
        "title": title, "type": "table",
        "transformations": [{"id": "organize",
                             "options": {"excludeByName": exclude}}],
    })


# ================================================================ OVERVIEW
row("Overview — how are we right now?")
stat("CPU usage (now)",
     "Process CPU share for this JVM right now (avg across selected services). "
     "100% = one full core busy; the JVM can exceed 100% across cores.",
     [(f"avg(process_cpu_usage{{{APP}}})", None, {"instant": True})],
     w=5, unit="percentunit", decimals=1, graph="area")
stat("Heap (used / max)",
     "JVM heap used now vs configured max (-Xmx). 'max' sums pools that report "
     "a real ceiling (some young-gen pools report -1 under G1).",
     [(f"sum(jvm_memory_used_bytes{{{APP},area=\"heap\"}})", "used", {"instant": True}),
      (f"sum(jvm_memory_max_bytes{{{APP},area=\"heap\"}} > 0)", "max", {"instant": True})],
     w=5, unit="decbytes", decimals=1, text_mode="value_and_name", color="blue")
stat("DB connections (active / max)",
     "HikariCP Postgres pool: connections checked out now vs configured maximum. "
     "Active sustained near max = the pool is the bottleneck.",
     [(f"sum(hikaricp_connections_active{{{APP}}})", "active", {"instant": True}),
      (f"sum(hikaricp_connections_max{{{APP}}})", "max", {"instant": True})],
     w=5, unit="short", text_mode="value_and_name", color="purple")
stat("HTTP requests in flight",
     "Server requests being processed right now (Micrometer LongTaskTimer). "
     "This is concurrency — NOT Tomcat sessions (we use stateless bearer tokens). "
     "Reads 0 when idle (the active series only exists while a request runs).",
     [(f"sum(http_server_requests_active_seconds_gcount{{{APP}}}) or vector(0)", None, {"instant": True})],
     w=5, unit="short", graph="area")
stat("HTTP requests (in window)",
     "Total HTTP server requests received over the dashboard's selected time "
     "range. Resizes when you change the time picker.",
     [(f"sum(increase(http_server_requests_seconds_count{{{APP}}}[$__range]))", None, {"instant": True})],
     w=4, unit="short", graph="area")

# ================================================================ SYSTEM HEALTH
row("System health (over time)")
ts("CPU usage (process vs system)",
   "JVM process CPU share and whole-host system CPU. Process near system = this "
   "JVM owns the load; system high but process low = a noisy neighbour.",
   [(f"process_cpu_usage{{{APP}}}", "{{application}} process", {}),
    (f"system_cpu_usage{{{APP}}}", "{{application}} system", {})],
   unit="percentunit")
ts("System load (1m) vs CPU count",
   "OS 1-minute load average plus the CPU-count line. Load above CPU count = "
   "host oversubscribed; threads waiting for CPU.",
   [(f"system_load_average_1m{{{APP}}}", "{{application}} load", {}),
    (f"system_cpu_count{{{APP}}}", "{{application}} cpus", {})])
ts("Heap memory used",
   "Total heap bytes in use per service. Per-pool breakdown is in Memory deep dive.",
   [(f"sum by(application)(jvm_memory_used_bytes{{{APP},area=\"heap\"}})", "{{application}}", {})],
   unit="decbytes")
ts("Non-heap memory used",
   "Metaspace, code cache, compressed class space, compiler buffers. Steady "
   "growth = classloader leak; sudden jump = a deploy.",
   [(f"sum by(application)(jvm_memory_used_bytes{{{APP},area=\"nonheap\"}})", "{{application}}", {})],
   unit="decbytes")
ts("GC pause time fraction",
   "Stop-the-world seconds per second of wall clock (smoothed 5m). 0.05 = 5% of "
   "the JVM was paused. Sustained > 0.10 hurts latency.",
   [(f"sum by(application)(rate(jvm_gc_pause_seconds_sum{{{APP}}}[5m]))", "{{application}}", {})],
   unit="percentunit")
ts("GC overhead",
   "Micrometer's GC overhead estimate (0-1): share of recent wall time the GC "
   "consumed. Sustained > 0.05 = GC is the bottleneck.",
   [(f"jvm_gc_overhead{{{APP}}}", "{{application}}", {})], unit="percentunit")
ts("Threads by state",
   "Live threads by state, stacked. RUNNABLE = CPU work; WAITING/TIMED_WAITING = "
   "idle/sleeping; BLOCKED = waiting on a monitor lock (concerning if sustained).",
   [(f"sort_desc(sum by(state)(jvm_threads_states_threads{{{APP}}}))", "{{state}}", {})],
   w=12, stack=True)
ts("Log events / s by level",
   "Logback emission rate per level (smoothed 5m). Spikes in ERROR/WARN are the "
   "first place to look during an incident.",
   [(f"sort_desc(sum by(level)(rate(logback_events_total{{{APP}}}[5m])))", "{{level}}", {})],
   w=12, unit="ops")
ts("Memory allocation rate",
   "Bytes/s allocated on the heap (young-gen pressure). High allocation forces "
   "frequent minor GCs even if the heap fits.",
   [(f"sum by(application)(rate(jvm_gc_memory_allocated_bytes_total{{{APP}}}[5m]))", "{{application}}", {})],
   unit="Bps")
ts("Disk usage",
   "Filesystem usage percent per monitored mountpoint. Watch sustained growth — "
   "log rotation gone wrong, runaway temp files.",
   [(f"(disk_total_bytes{{{APP}}} - disk_free_bytes{{{APP}}}) / disk_total_bytes{{{APP}}} * 100",
     "{{application}} {{path}}", {})], unit="percent")
ts("Open file descriptors",
   "Open FDs (sockets, files, pipes) vs the OS limit (ulimit -n). Climbing toward "
   "max = FD leak; sudden jump = a burst of connections.",
   [(f"process_files_open_files{{{APP}}}", "{{application}} open", {}),
    (f"process_files_max_files{{{APP}}}", "{{application}} max", {})])

# ================================================================ MEMORY DEEP DIVE
row("Memory deep dive")
ts("Heap by pool (id)",
   "Heap bytes used per pool, stacked. Under G1: Old Gen (long-lived), Eden "
   "(allocation buffer), Survivor. Growing Old Gen alone = leak; growing Eden + "
   "frequent minor GC = healthy churn.",
   [(f"sort_desc(sum by(id)(jvm_memory_used_bytes{{{APP},area=\"heap\"}}))", "{{id}}", {})],
   w=12, stack=True, unit="decbytes")
ts("Non-heap by pool (id)",
   "Non-heap bytes per pool: Metaspace, Code Cache, Compressed Class Space, "
   "Compiler buffers. Stacked largest at bottom.",
   [(f"sort_desc(sum by(id)(jvm_memory_used_bytes{{{APP},area=\"nonheap\"}}))", "{{id}}", {})],
   w=12, stack=True, unit="decbytes")
ts("Heap live data (post-GC)",
   "Heap that survives a full GC (live set) vs the max promoted region. Live "
   "trending up = real memory growth, not just allocation churn.",
   [(f"jvm_gc_live_data_size_bytes{{{APP}}}", "{{application}} live", {}),
    (f"jvm_gc_max_data_size_bytes{{{APP}}}", "{{application}} max", {})],
   unit="decbytes")
ts("Direct buffer used",
   "DirectByteBuffer usage (off-heap NIO). Steady growth here can OOM the "
   "container without showing up in heap.",
   [(f"sum by(application)(jvm_buffer_memory_used_bytes{{{APP},id=\"direct\"}})", "{{application}}", {})],
   unit="decbytes")
ts("Memory usage after GC (long-lived)",
   "Fraction of the long-lived pool occupied immediately after a GC. Trending up "
   "= the true working set is growing (not just churn).",
   [(f"jvm_memory_usage_after_gc{{{APP}}}", "{{application}} {{pool}}", {})],
   unit="percentunit")

# ================================================================ GC DEEP DIVE
row("GC deep dive")
ts("GC max pause (upper) per cycle",
   "Worst single STW pause duration per GC cycle, per action. Spikes here become "
   "latency outliers in HTTP responses.",
   [(f"jvm_gc_pause_seconds_max{{{APP}}}", "{{application}} {{action}} ({{gc}})", {})],
   w=12, unit="s")
ts("GC cycles / s",
   "GC cycles per second by action (end of minor/major GC). Sustained high rate = "
   "young gen too small for the allocation rate, or memory pressure.",
   [(f"sum by(action,gc)(rate(jvm_gc_pause_seconds_count{{{APP}}}[5m]))", "{{action}} ({{gc}})", {})],
   w=12, unit="ops")
ts("GC pause seconds / s by action",
   "Stop-the-world seconds per second split by GC action. Lets you see whether "
   "minor or major collections dominate the pause budget.",
   [(f"sum by(action)(rate(jvm_gc_pause_seconds_sum{{{APP}}}[5m]))", "{{action}}", {})],
   unit="percentunit")
ts("Memory promoted rate (-> old gen)",
   "Bytes/s promoted from young to old gen. High promotion = objects living long "
   "enough to survive several minor GCs — big allocations, caches, session data.",
   [(f"sum by(application)(rate(jvm_gc_memory_promoted_bytes_total{{{APP}}}[5m]))", "{{application}}", {})],
   unit="Bps")
ts("JIT compilation time (cumulative)",
   "Cumulative ms in the JIT compiler (C1/C2). Should plateau a few minutes after "
   "startup. Sustained growth post-warmup = JIT thrashing.",
   [(f"sum by(application, compiler)(jvm_compilation_time_ms_total{{{APP}}})", "{{application}} {{compiler}}", {})],
   unit="ms")

# ================================================================ HTTP SERVER
row("HTTP Server")
ts("Request rate (5m) by status",
   "Inbound HTTP request rate grouped by status code, stacked. Usually 200, then "
   "4xx, then 5xx.",
   [(f"sort_desc(sum by(status)(rate(http_server_requests_seconds_count{{{APP}}}[5m])))", "{{status}}", {})],
   w=12, unit="reqps", stack=True)
ts("Request rate (5m) by method",
   "Same as by-status but grouped by HTTP method. Useful to spot a sudden spike "
   "of writes.",
   [(f"sort_desc(sum by(method)(rate(http_server_requests_seconds_count{{{APP}}}[5m])))", "{{method}}", {})],
   w=12, unit="reqps", stack=True)
ts("HTTP latency by URI (p50 / p95 / p99)",
   "Server-side latency percentiles computed from the native histogram buckets, "
   "per URI. Compare p50 (typical user) vs p95/p99 (slow tail).",
   [(f"histogram_quantile(0.50, sum by(le,uri)(rate(http_server_requests_seconds_bucket{{{APP}}}[5m])))", "{{uri}} p50", {}),
    (f"histogram_quantile(0.95, sum by(le,uri)(rate(http_server_requests_seconds_bucket{{{APP}}}[5m])))", "{{uri}} p95", {}),
    (f"histogram_quantile(0.99, sum by(le,uri)(rate(http_server_requests_seconds_bucket{{{APP}}}[5m])))", "{{uri}} p99", {})],
   w=12, unit="s")
ts("Error rate (4xx / 5xx share)",
   "Fraction of requests returning 4xx and 5xx. 5xx is server fault; 4xx is "
   "usually client/auth. Numerator guarded with 'or vector(0)' so it reads 0 "
   "(not 'no data') when there are zero errors but traffic is flowing.",
   [(f"(sum(rate(http_server_requests_seconds_count{{{APP},status=~\"4..\"}}[5m])) or vector(0)) / sum(rate(http_server_requests_seconds_count{{{APP}}}[5m]))", "4xx rate", {}),
    (f"(sum(rate(http_server_requests_seconds_count{{{APP},status=~\"5..\"}}[5m])) or vector(0)) / sum(rate(http_server_requests_seconds_count{{{APP}}}[5m]))", "5xx rate", {})],
   w=12, unit="percentunit")
ts("Concurrent requests in flight",
   "Server requests processed simultaneously, per service. Sustained high = "
   "request rate exceeds per-request latency capacity — scale out or speed up. "
   "Flat 0 when idle.",
   [(f"sum by(application)(http_server_requests_active_seconds_gcount{{{APP}}}) or vector(0)", "{{application}}", {})],
   w=12, unit="short")
ts("Request rate (5m) by URI",
   "Inbound request rate per endpoint. The busiest URIs are where optimisation "
   "and caching pay off most.",
   [(f"sort_desc(sum by(uri)(rate(http_server_requests_seconds_count{{{APP}}}[5m])))", "{{uri}}", {})],
   w=12, unit="reqps")
bargauge("Requests by endpoint (window total)",
         "Top 20 (uri, method, status) tuples by request count over the selected "
         "time range. Resizes with the time picker.",
         f"topk(20, sum by(uri,method,status)(increase(http_server_requests_seconds_count{{{APP}}}[$__range])))")
table("Top URIs by request count (window total)",
      "Tabular endpoint breakdown — full URI text, sortable columns, exportable "
      "as CSV.",
      f"topk(20, sum by(uri,method,status)(increase(http_server_requests_seconds_count{{{APP}}}[$__range])))")

# ================================================================ DB POOL
row("Database pool (HikariCP)")
ts("Connections by state",
   "Hikari connections per state: active (checked out), idle (in pool), pending "
   "(threads WAITING for a connection — saturation!), total.",
   [(f"sum by(application)(hikaricp_connections_active{{{APP}}})", "{{application}} active", {}),
    (f"sum by(application)(hikaricp_connections_idle{{{APP}}})", "{{application}} idle", {}),
    (f"sum by(application)(hikaricp_connections_pending{{{APP}}})", "{{application}} pending", {}),
    (f"sum by(application)(hikaricp_connections{{{APP}}})", "{{application}} total", {})],
   w=12)
ts("Pool bounds (min / max)",
   "Configured pool bounds (minimum-idle and maximum-pool-size). Compare to the "
   "active count on the left.",
   [(f"sum by(application)(hikaricp_connections_min{{{APP}}})", "{{application}} min", {}),
    (f"sum by(application)(hikaricp_connections_max{{{APP}}})", "{{application}} max", {})],
   w=12)
ts("DB acquire latency (avg / max)",
   "Time to obtain a connection from the pool. Climbing = pool saturation or "
   "Postgres slow. Sustained high = grow the pool or release connections faster.",
   [(f"rate(hikaricp_connections_acquire_seconds_sum{{{APP}}}[5m]) / rate(hikaricp_connections_acquire_seconds_count{{{APP}}}[5m])", "{{application}} avg", {}),
    (f"hikaricp_connections_acquire_seconds_max{{{APP}}}", "{{application}} max", {})],
   unit="s")
ts("Acquire rate / s",
   "Rate of connection check-outs from the pool. Each HTTP request that hits the "
   "DB typically acquires one.",
   [(f"sum by(application)(rate(hikaricp_connections_acquire_seconds_count{{{APP}}}[5m]))", "{{application}}", {})],
   unit="ops")
ts("Connection hold time + timeouts",
   "avg = average time a connection is held before return. timeouts/s = threads "
   "that gave up waiting (pool fully saturated past connectionTimeout).",
   [(f"rate(hikaricp_connections_usage_seconds_sum{{{APP}}}[5m]) / rate(hikaricp_connections_usage_seconds_count{{{APP}}}[5m])", "{{application}} hold avg", {}),
    (f"rate(hikaricp_connections_timeout_total{{{APP}}}[5m])", "{{application}} timeouts/s", {})],
   unit="s")

# ================================================================ CACHE
row("Cache (Caffeine)")
ts("Cache hit rate (%) by cache",
   "Hit ratio per cache: hits / (hits + misses), smoothed 5m. Low or falling = "
   "cache thrash or cold cache after eviction.",
   [(f"sum by(cache)(rate(cache_gets_total{{{APP},result=\"hit\"}}[5m])) / (sum by(cache)(rate(cache_gets_total{{{APP},result=\"hit\"}}[5m])) + sum by(cache)(rate(cache_gets_total{{{APP},result=\"miss\"}}[5m])))", "{{cache}}", {})],
   w=8, unit="percentunit")
ts("Cache hits vs misses (/s)",
   "Get rate split into hits and misses per cache. Lots of gets + few misses = "
   "healthy. Rising misses = working set outgrew the cache.",
   [(f"sum by(cache)(rate(cache_gets_total{{{APP},result=\"hit\"}}[5m]))", "{{cache}} hits", {}),
    (f"sum by(cache)(rate(cache_gets_total{{{APP},result=\"miss\"}}[5m]))", "{{cache}} misses", {})],
   w=8, unit="ops")
gauge("Total cache hit rate (5m)",
      "Overall hit ratio across all caches. Below ~0.5 means the cache is doing "
      "little useful work.",
      [(f"sum(rate(cache_gets_total{{{APP},result=\"hit\"}}[5m])) / sum(rate(cache_gets_total{{{APP}}}[5m]))", "hit rate", {})],
      w=8)
ts("Cache size (entries)",
   "Live entry count per cache. Flat at the configured maximum = cache is full "
   "and evicting to make room.",
   [(f"cache_size{{{APP}}}", "{{cache}}", {})], w=8)
ts("Cache evictions (/s)",
   "Entries evicted per second per cache. A spike = bulk write triggered "
   "invalidation, or the cache is too small (size-based eviction).",
   [(f"sum by(cache)(rate(cache_evictions_total{{{APP}}}[5m]))", "{{cache}}", {})],
   w=8, unit="ops")
ts("Cache puts (/s)",
   "Entries written per second per cache. High puts with low hit rate = we keep "
   "filling the cache but rarely read before eviction.",
   [(f"sum by(cache)(rate(cache_puts_total{{{APP}}}[5m]))", "{{cache}}", {})],
   w=8, unit="ops")

# ================================================================ SPRING DATA REPO
row("Spring Data Repository")
ts("Invocations (window total) by repository",
   "Spring Data repository method invocations per repository over the selected "
   "time range. The hot repositories are your DB workload.",
   [(f"sort_desc(sum by(repository)(increase(spring_data_repository_invocations_seconds_count{{{APP}}}[$__range])))", "{{repository}}", {})],
   w=12, unit="short")
ts("Repository latency (avg / max)",
   "Per-repository method latency: avg = rate(sum)/rate(count); max = worst step. "
   "Spikes = lock contention, missing index, or cold cache.",
   [(f"sum by(repository)(rate(spring_data_repository_invocations_seconds_sum{{{APP}}}[5m])) / sum by(repository)(rate(spring_data_repository_invocations_seconds_count{{{APP}}}[5m]))", "{{repository}} avg", {}),
    (f"max by(repository)(spring_data_repository_invocations_seconds_max{{{APP}}})", "{{repository}} max", {})],
   w=12, unit="s")
bargauge("Top repository methods (window total)",
         "Top 20 repository.method calls over the selected range. The biggest bars "
         "are your most-called queries.",
         f"topk(20, sum by(repository,method)(increase(spring_data_repository_invocations_seconds_count{{{APP}}}[$__range])))")
table("Repository invocations (window total)",
      "Same top-20 list as a table, with sortable columns including state "
      "(SUCCESS / ERROR).",
      f"topk(20, sum by(repository,method,state)(increase(spring_data_repository_invocations_seconds_count{{{APP}}}[$__range])))")

# ================================================================ SPRING SECURITY
row("Spring Security")
ts("Authorization decisions (5m)",
   "Authorization outcomes (true = GRANTED, false = DENIED) per second. Sustained "
   "DENIED = a client hitting endpoints it shouldn't, or a role change broke a user.",
   [(f"sort_desc(sum by(spring_security_authorization_decision)(rate(spring_security_authorizations_seconds_count{{{APP}}}[5m])))", "decision={{spring_security_authorization_decision}}", {})],
   w=8, unit="ops")
ts("HTTP secured requests (/s)",
   "Requests that passed through Spring Security's filter chain. Should mirror "
   "inbound HTTP volume.",
   [(f"sum(rate(spring_security_http_secured_requests_seconds_count{{{APP}}}[5m]))", "secured req/s", {})],
   w=8, unit="ops")
ts("Top filter chains by avg latency",
   "Top 10 security filters by mean processing time. Most are sub-millisecond; "
   "the auth/bearer-token filters are usually the heaviest.",
   [(f"topk(10, sum by(spring_security_reached_filter_name)(rate(spring_security_filterchains_seconds_sum{{{APP}}}[5m])) / sum by(spring_security_reached_filter_name)(rate(spring_security_filterchains_seconds_count{{{APP}}}[5m])))", "{{spring_security_reached_filter_name}}", {})],
   w=8, unit="s")

# ================================================================ SCHEDULED TASKS
row("Scheduled tasks (@Scheduled)")
ts("Scheduled execution rate (/s)",
   "Rate of @Scheduled method executions (e.g. RoutineSnapshotScheduler). Empty "
   "until a scheduler fires after process start.",
   [(f"sum by(application)(rate(tasks_scheduled_execution_seconds_count{{{APP}}}[5m]))", "{{application}}", {})],
   w=12, unit="ops")
ts("Scheduled execution duration (avg / max)",
   "Average and worst execution time for @Scheduled jobs. A scheduler taking "
   "longer than its interval will overlap or fall behind.",
   [(f"rate(tasks_scheduled_execution_seconds_sum{{{APP}}}[5m]) / rate(tasks_scheduled_execution_seconds_count{{{APP}}}[5m])", "avg", {}),
    (f"tasks_scheduled_execution_seconds_max{{{APP}}}", "max", {})],
   w=12, unit="s")

# ================================================================ DIAGNOSTICS
row("Diagnostics")
ts("Uptime",
   "Seconds since process start, per service. A drop to 0 = a restart. Sanity "
   "check that nothing crash-looped recently.",
   [(f"process_uptime_seconds{{{APP}}}", "{{application}}", {})], w=8, unit="s")
ts("Classes loaded vs unloaded",
   "Classes currently loaded vs cumulative unloaded. Sustained growth in loaded "
   "without matching unloaded = classloader leak.",
   [(f"jvm_classes_loaded_classes{{{APP}}}", "{{application}} loaded", {}),
    (f"jvm_classes_unloaded_classes_total{{{APP}}}", "{{application}} unloaded", {})],
   w=8)
ts("Thread count (live / daemon / peak)",
   "Live, daemon, and peak thread counts. Peak ratcheting up without coming back "
   "= a thread leak (often unbounded executors).",
   [(f"jvm_threads_live_threads{{{APP}}}", "{{application}} live", {}),
    (f"jvm_threads_daemon_threads{{{APP}}}", "{{application}} daemon", {}),
    (f"jvm_threads_peak_threads{{{APP}}}", "{{application}} peak", {})],
   w=8)

# ================================================================ DASHBOARD
dashboard = {
    "annotations": {"list": [{
        "builtIn": 1, "enable": True, "hide": True,
        "iconColor": "rgba(0, 211, 255, 1)",
        "name": "Annotations & Alerts", "type": "dashboard"}]},
    "description": "Consolidated Beyou backend service-health board — overview "
                   "cards, JVM/system, memory & GC deep dives, HTTP server, "
                   "HikariCP pool, Caffeine cache, Spring Data, Spring Security, "
                   "scheduled tasks and diagnostics. Replaces the old per-area "
                   "dashboards.",
    "editable": True, "fiscalYearStartMonth": 0, "graphTooltip": 1, "links": [],
    "panels": panels, "refresh": "30s", "schemaVersion": 39,
    "tags": ["beyou", "service-health", "consolidated"],
    "templating": {"list": [{
        "allValue": ".*",
        "current": {"text": "All", "value": "$__all"},
        "datasource": DS,
        "definition": "label_values(application)",
        "includeAll": True, "label": "Application", "multi": True,
        "name": "application", "options": [],
        "query": {"query": "label_values(application)", "refId": "A"},
        "refresh": 2, "sort": 1, "type": "query"}]},
    "time": {"from": "now-6h", "to": "now"}, "timepicker": {},
    "timezone": "browser",
    "title": "Beyou — Service Health (consolidated)",
    "uid": "beyou-service-health",
}

out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "beyou-service-health.json")
with open(out, "w") as f:
    json.dump(dashboard, f, indent=2)
    f.write("\n")
print(f"wrote {out}: {len(panels)} panels "
      f"({sum(1 for p in panels if p['type'] == 'row')} rows)")
