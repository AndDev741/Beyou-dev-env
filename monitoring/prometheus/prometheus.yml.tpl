global:
  scrape_interval: 15s
  evaluation_interval: 15s

# No rule_files and no alerting.alertmanagers block here, deliberately: telling
# people is GlitchTip's job in this stack (its uptime monitors page a human via
# the alert rules that bootstrap-glitchtip.py wires up). Prometheus stays the
# observation layer — every target below makes an outage visible in Grafana
# and answerable in Explore.

# This file is a TEMPLATE: @VAR@ tokens are replaced by the entrypoint in
# docker-compose.monitoring.yml (a sh/sed render) before Prometheus loads it.
# Prometheus itself does not expand environment variables in config files.
# The values come from the prometheus service's environment, which compose
# fills with compose-level defaults — so a deployment that maps the exporter
# ports differently changes one line in .env, and a deployment that does not
# run this compose stack sets the same variables itself.
#
# Render check after editing:
#   sed -e 's|@CADVISOR_PORT@|8080|g' -e 's|@NODE_EXPORTER_PORT@|9100|g' \
#       -e 's|@POSTGRES_EXPORTER_PORT@|9187|g' \
#       -e 's|@WATCHTOWER_API_TOKEN@|x|g' \
#       prometheus.yml.tpl > /tmp/p.yml && promtool check config /tmp/p.yml

scrape_configs:
  - job_name: "beyou-backend"
    metrics_path: "/actuator/prometheus"
    static_configs:
      - targets: ["backend:9091"]

  # Watches the watcher. Every alarm in this stack is raised BY GlitchTip: the
  # uptime and heartbeat monitors live in its database, notifications leave its
  # process, and the backend, web and mobile apps all POST their errors to it.
  # So GlitchTip cannot be the thing that reports a GlitchTip outage — when it
  # wedges, every one of those signals goes silent at once and the stack reads as
  # calm. Prometheus is the only component here that is not GlitchTip, which makes
  # `up{job="glitchtip"}` the one honest liveness signal for the collector.
  #
  # No blackbox exporter needed: the image already bundles django-prometheus, and
  # the endpoint is switched on by ENABLE_OBSERVABILITY_API in
  # docker-compose.monitoring.yml. Reached over beyou_net, which both containers
  # share; the CONTAINER port (8000), never the published one.
  #
  # Scope of the signal, stated honestly: `up` proves the process is accepting
  # and routing HTTP. The view does run a DB aggregate, but it is cached in
  # Valkey for an hour, so most scrapes serve from cache and a database failure
  # is only caught on the miss. Treat this as liveness, not a deep health check;
  # the exported glitchtip_organizations / glitchtip_projects_total gauges are
  # counts, and upstream computes them with a join that inflates the org number.
  - job_name: "glitchtip"
    metrics_path: "/metrics"
    static_configs:
      - targets: ["glitchtip:8000"]

  # Watches the log pipeline, for the same reason job "glitchtip" watches the
  # error collector: a dead log store fails SILENT, not loud. Queries error in
  # Grafana only when someone looks; ingestion just stops. `up{job="loki"}` and
  # `up{job="alloy"}` are the signals that logging quietly died — and Alloy's
  # own `loki_write_dropped_entries_total` says whether logs are being lost
  # while Loki is down (Alloy retries with backoff, but its send buffer is
  # finite and drops oldest-first once full).
  - job_name: "loki"
    metrics_path: "/metrics"
    static_configs:
      - targets: ["loki:3100"]

  - job_name: "alloy"
    metrics_path: "/metrics"
    static_configs:
      - targets: ["alloy:12345"]

  # --- fleet jobs: the containers dashboard's source of truth -----------------
  # One job per surface, all internal-only (no published ports). Availability
  # here is `up`; deep health per service is GlitchTip's monitors.

  # Self-scrape: makes `up{job="prometheus"}` exist instead of relying on
  # guesses when the dashboard's endpoint grid is looked at.
  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]

  # No "frontend" job, deliberately: Vite's dev server rejects scrapes whose
  # Host header is not localhost or an IP (a "frontend:3000" Host answers 403),
  # and Prometheus cannot override the Host header it sends. Frontend
  # availability therefore lives where it already was: the GlitchTip TCP
  # monitor ("Beyou web frontend"), which needs no HTTP semantics.

  # cAdvisor: per-container resources (CPU, memory, network, disk) labeled with
  # the Compose service/project. Port via CADVISOR_PORT, default 8080.
  - job_name: "cadvisor"
    static_configs:
      - targets: ["cadvisor:@CADVISOR_PORT@"]

  # Host-level metrics: CPU, load, memory, disk, network. Port via
  # NODE_EXPORTER_PORT, default 9100.
  - job_name: "node-exporter"
    static_configs:
      - targets: ["node-exporter:@NODE_EXPORTER_PORT@"]

  # The app DB from the DB's own side (pg_up, connections, cache hit ratio,
  # deadlocks). Port via POSTGRES_EXPORTER_PORT, default 9187.
  - job_name: "postgres-exporter"
    static_configs:
      - targets: ["postgres-exporter:@POSTGRES_EXPORTER_PORT@"]

  # Grafana's own /metrics (enabled via GF_METRICS_ENABLED in the overlay).
  # `up` here is "Grafana's process answered"; /api/health semantics belong to
  # the GlitchTip monitor.
  - job_name: "grafana"
    metrics_path: "/metrics"
    static_configs:
      - targets: ["grafana:3000"]

  # watchtower's /v1/metrics, which only exists when the metrics endpoint is
  # enabled via --http-api-endpoints (see docker-compose.prod.yml, which also
  # explains why `update` must not join that list without
  # --http-api-periodic-polls). Bearer token is the same WATCHTOWER_API_TOKEN
  # the updater requires. In dev there is no watchtower container, so this
  # target stays down by design — truthful, not misconfigured.
  - job_name: "watchtower"
    metrics_path: "/v1/metrics"
    authorization:
      type: Bearer
      credentials: "@WATCHTOWER_API_TOKEN@"
    static_configs:
      - targets: ["watchtower:8080"]
