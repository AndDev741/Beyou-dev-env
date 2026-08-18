#!/usr/bin/env python3
"""Generate the Beyou rate-limit Grafana dashboard.

Two datasources on purpose, because the question splits in two:

  * Prometheus answers "which limit is biting, and how hard" — the backend's
    beyou.ratelimit.rejected counter, tagged with the tier and nothing else.
  * Loki answers "who" — the WARN line the filter writes alongside the counter,
    which is the only place the bucket key (a user id or an address) appears.

The split is deliberate rather than incidental. Tagging the metric with the
bucket key would give it unbounded cardinality, so a caller rotating addresses
could mint Prometheus series at will — a denial of service against the
monitoring instead of a defence of the app. Keeping identity in the log means
the dashboard stays cheap and the forensics stay possible.

Run:  python3 .gen_ratelimit_dashboard.py  ->  writes beyou-rate-limits.json
"""
import json
import os

PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}

APP = 'application=~"$application"'
# Micrometer publishes the counter beyou.ratelimit.rejected as this series.
REJECTED = "beyou_ratelimit_rejected_total"
# The filter's line: Rate limit rejected POST /auth/login — tier=auth key=auth:1.2.3.4 retryAfter=812s
LINE = 'Rate limit rejected'
STREAM = '{project=~"$project", service=~"$service"}'
# Backticks keep the pattern raw, so LogQL sees a single backslash.
PARSE = '| regexp `tier=(?P<tier>\\S+) key=(?P<key>\\S+) retryAfter=(?P<retry>\\d+)s`'

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


def _targets(ds, exprs):
    out = []
    for i, (expr, legend) in enumerate(exprs):
        t = {"datasource": ds, "expr": expr, "refId": chr(ord("A") + i)}
        if legend is not None:
            t["legendFormat"] = legend
        out.append(t)
    return out


def stat(title, desc, exprs, ds=PROM, w=6, h=5, unit="short", color="green",
         graph="area"):
    panels.append({
        "datasource": ds, "description": desc,
        "fieldConfig": {"defaults": {
            "color": {"mode": "fixed", "fixedColor": color}, "mappings": [],
            "unit": unit, "decimals": 0,
            "thresholds": {"mode": "absolute",
                           "steps": [{"color": color, "value": None}]}},
            "overrides": []},
        "gridPos": _place(w, h), "id": _next_id(),
        "options": {"colorMode": "value", "graphMode": graph,
                    "justifyMode": "auto", "orientation": "auto",
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "",
                                      "values": False},
                    "textMode": "auto", "wideLayout": True},
        "targets": _targets(ds, exprs), "title": title, "type": "stat",
    })


def ts(title, desc, exprs, ds=PROM, w=12, h=8, unit="short", stack=False,
       fill=10):
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
    panels.append({
        "datasource": ds, "description": desc,
        "fieldConfig": {"defaults": {
            "color": {"mode": "palette-classic"}, "custom": custom,
            "mappings": [], "unit": unit,
            "thresholds": {"mode": "absolute",
                           "steps": [{"color": "green", "value": None}]}},
            "overrides": []},
        "gridPos": _place(w, h), "id": _next_id(),
        "options": {"legend": {"calcs": ["sum"], "displayMode": "table",
                               "placement": "right", "showLegend": True},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
        "targets": _targets(ds, exprs), "title": title, "type": "timeseries",
    })


def bargauge(title, desc, exprs, ds=PROM, w=12, h=8, unit="short"):
    panels.append({
        "datasource": ds, "description": desc,
        "fieldConfig": {"defaults": {
            "color": {"mode": "continuous-GrYlRd"}, "decimals": 0,
            "mappings": [], "unit": unit,
            "thresholds": {"mode": "absolute",
                           "steps": [{"color": "green", "value": None}]}},
            "overrides": []},
        "gridPos": _place(w, h), "id": _next_id(),
        "options": {"displayMode": "gradient", "maxVizHeight": 300,
                    "minVizHeight": 16, "minVizWidth": 8,
                    "namePlacement": "auto", "orientation": "horizontal",
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "",
                                      "values": False},
                    "showUnfilled": True, "sizing": "auto", "valueMode": "color"},
        "targets": _targets(ds, exprs), "title": title, "type": "bargauge",
    })


def logs(title, desc, expr, w=24, h=12):
    panels.append({
        "datasource": LOKI, "description": desc,
        "gridPos": _place(w, h), "id": _next_id(),
        "options": {"dedupStrategy": "none", "enableLogDetails": True,
                    "prettifyLogMessage": False, "showCommonLabels": False,
                    "showLabels": False, "showTime": True,
                    "sortOrder": "Descending", "wrapLogMessage": True},
        "targets": [{"datasource": LOKI, "expr": expr, "refId": "A"}],
        "title": title, "type": "logs",
    })


# ==================================================================== OVERVIEW
row("Is anything being throttled")

stat("Rejections in range",
     "Total requests this filter turned away over the selected window. Zero is "
     "the normal reading — a limit that never bites is a limit sized for real "
     "use. A number here is either abuse or a tier sized too tightly, and the "
     "tier panels below say which.",
     [(f"sum(increase({REJECTED}{{{APP}}}[$__range]))", None)],
     color="orange")

stat("Tiers rejecting",
     "How many distinct tiers turned anyone away in the window. More than one "
     "at a time usually means a single caller hammering everything rather than "
     "one endpoint being mis-sized.",
     [(f"count(count by (tier) (increase({REJECTED}{{{APP}}}[$__range]) > 0))", None)],
     color="yellow")

stat("Distinct callers rejected",
     "Counted from the log, not the metric — the metric deliberately carries no "
     "identity. One caller against many is abuse; many callers at once is a "
     "limit that needs raising.",
     [(f'count(sum by (key) (count_over_time({STREAM} |= `{LINE}` {PARSE} [$__range])))', None)],
     ds=LOKI, color="red")

stat("Peak rejections / min",
     "Busiest minute in the window. Useful for sizing: a brief spike against a "
     "greedily-refilling bucket is very different from a sustained wall.",
     [(f"max(sum(rate({REJECTED}{{{APP}}}[1m])) * 60)", None)],
     color="purple")

# ================================================================ WHICH LIMIT
row("Which limit is biting")

ts("Rejections per minute by tier",
   "Rate of 429s per tier. auth spiking on its own is credential stuffing; "
   "agent or onboarding spiking is someone spending your LLM budget; write "
   "spiking is usually a client retry loop, not a person.",
   [(f"sum by (tier) (rate({REJECTED}{{{APP}}}[5m])) * 60", "{{tier}}")],
   unit="short", stack=True)

bargauge("Total rejections by tier",
         "Totals over the window, so a tier that bit once does not look like a "
         "tier that bit constantly. Tiers with no rejections are absent rather "
         "than zero — the counter is only created on the first rejection.",
         [(f"sum by (tier) (increase({REJECTED}{{{APP}}}[$__range]))", "{{tier}}")])

# =================================================================== WHO
row("Who is being throttled")

ts("Top callers rejected",
   "The ten bucket keys turned away most often, parsed out of the filter's WARN "
   "line. A key is tier:identity — auth:<address> for the IP-keyed tiers, "
   "agent:<userId> and friends for the per-user ones. This is the panel the "
   "metric cannot give you, and the reason the log line exists.",
   [(f'topk(10, sum by (key) (count_over_time({STREAM} |= `{LINE}` {PARSE} [$__auto])))',
     "{{key}}")],
   ds=LOKI, w=24, h=9, stack=True)

logs("Rejection log",
     "Every rejection, newest first. Each line carries the method, the path, the "
     "tier, the bucket key and the Retry-After the caller was handed — enough to "
     "tell a user who hit a wall from a script that kept walking into it.",
     f'{STREAM} |= `{LINE}`')

# ================================================================= DASHBOARD
dashboard = {
    "annotations": {"list": [{
        "builtIn": 1, "enable": True, "hide": True,
        "iconColor": "rgba(0, 211, 255, 1)",
        "name": "Annotations & Alerts", "type": "dashboard"}]},
    "description": "Who is hitting the Beyou rate limits, and which tier turned "
                   "them away. Prometheus supplies the tier-level counts; Loki "
                   "supplies the identity, because tagging the metric with the "
                   "bucket key would give it unbounded cardinality.",
    "editable": True, "fiscalYearStartMonth": 0, "graphTooltip": 1, "links": [],
    "panels": panels, "refresh": "30s", "schemaVersion": 39,
    "tags": ["beyou", "rate-limits", "security"],
    "templating": {"list": [
        {"allValue": ".*",
         "current": {"text": "All", "value": "$__all"},
         "datasource": PROM,
         "definition": "label_values(application)",
         "includeAll": True, "label": "Application", "multi": True,
         "name": "application", "options": [],
         "query": {"query": "label_values(application)", "refId": "A"},
         "refresh": 2, "sort": 1, "type": "query"},
        {"current": {"selected": True, "text": ["All"], "value": ["$__all"]},
         "datasource": LOKI,
         "includeAll": True, "label": "Project", "multi": True,
         "name": "project",
         "query": {"label": "project", "refId":
                   "LokiVariableQueryEditor-VariableQuery", "stream": "",
                   "type": 1},
         "refresh": 2, "type": "query"},
        {"current": {"selected": True, "text": ["backend"], "value": ["backend"]},
         "datasource": LOKI,
         "includeAll": True, "label": "Service", "multi": True,
         "name": "service",
         "query": {"label": "service", "refId":
                   "LokiVariableQueryEditor-VariableQuery", "stream": "",
                   "type": 1},
         "refresh": 2, "type": "query"},
    ]},
    "time": {"from": "now-6h", "to": "now"}, "timepicker": {},
    "timezone": "browser",
    "title": "Beyou — Rate Limits",
    "uid": "beyou-rate-limits",
}

out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "beyou-rate-limits.json")
with open(out, "w") as f:
    json.dump(dashboard, f, indent=2)
    f.write("\n")
print(f"wrote {out}: {len(panels)} panels "
      f"({sum(1 for p in panels if p['type'] == 'row')} rows)")
