# Beyou Dev Environment

This repo orchestrates the Beyou backend, frontend, and Postgres for local development and a production-like run using Docker Compose.

## Prerequisites
- Docker Desktop or Docker Engine with `docker compose`

## Layout
Clone all the required repositories in a single folder

```bash
git clone https://github.com/AndDev741/Beyou-backend-spring.git
git clone https://github.com/AndDev741/Beyou-Frontend.git
git clone https://github.com/AndDev741/Beyou-dev-env.git
```

Will be like this:
```
/your-folder-of-preference
  beyou-dev-env/
  Beyou-backend-spring/
  Beyou-Frontend/
```

## Setup
1. Copy `.env.example` to `.env` and fill in required secrets.
2. Start in dev mode or prod mode (see below).

## Dev mode (hot reload)
```
./scripts/up-dev.sh
```

## Prod-like mode (build + nginx)
```
./scripts/up-prod.sh
```

## Stop services
```
./scripts/down.sh dev
```
```
./scripts/down.sh prod
```

## Reset Postgres data
```
./scripts/reset-db.sh
```

## Monitoring & error telemetry

`docker-compose.monitoring.yml` is an optional overlay carrying Prometheus,
Grafana, GlitchTip (self-hosted error telemetry, Sentry-API compatible), and
Loki + Alloy (unified log aggregation).

```
./scripts/up-dev.sh --monitoring
./scripts/down.sh dev --monitoring
```

The division of labour: **Prometheus** answers "how is it performing",
**GlitchTip** answers "what broke" (error events, including from real users'
browsers), **Loki** answers "what happened" (every log line every container
printed, queryable for 30 days). All three surface in the same Grafana.

### Unified logs (Loki + Alloy)

Zero app configuration: anything a container writes to stdout is collected.
Alloy tails every container in the Beyou compose projects through the Docker
API and pushes to Loki; Grafana queries Loki as a provisioned datasource. That
covers the Spring backend, the frontend (Vite in dev, nginx in prod), Postgres,
and the monitoring services themselves — identically in dev and prod, because
it is the same overlay.

Where to look:

- **Grafana → Dashboards → Beyou Logs** — volume/error charts plus a filterable
  log browser (project, service, level, free-text search).
- **Grafana → Explore → Loki** for ad-hoc queries. The bread and butter:

  ```logql
  {service="backend"}                                  # everything the backend printed
  {service="backend"} | detected_level="error"         # errors only
  {service=~"backend|frontend"} |~ "(?i)nullpointer"   # regex search across services
  {project="beyou-e2e"}                                # the e2e stack, when it runs
  ```

  `detected_level` is attached server-side by Loki (it parses JSON, logfmt and
  plain-text keywords), which is why neither the apps nor Alloy do any log
  parsing.

Behaviour worth knowing before you trust it:

- **Scope**: Alloy keeps only containers whose Compose project name starts with
  `beyou` (case-insensitive) — this host runs unrelated stacks, and their logs
  do not belong in a Loki that anyone with Grafana access can query. The
  project name comes from the checkout directory name; deploy this repo from a
  directory not starting with `beyou` and logs silently stop flowing — fix the
  directory name or the `keep` rule in `monitoring/alloy/config.alloy`.
- **Retention**: 30 days, enforced by Loki's compactor
  (`monitoring/loki/loki.yml`), same number as `GLITCHTIP_RETENTION_DAYS`.
  Log history now lives in Loki's `loki_data` volume — `docker logs` on the
  host only holds the rotated tail (10m × 3 files per container, set in every
  compose file).
- **Exposure**: Loki has no host port at all — its push/query API is
  unauthenticated, so its only clients are Alloy and Grafana over `beyou_net`,
  and the thing with a login (Grafana) is the read path. Alloy's debugging UI
  (pipeline health, discovered containers) is loopback-bound on
  `ALLOY_PORT` (12345), same treatment as Prometheus.
- **Own liveness**: Prometheus scrapes both (`up{job="loki"}`,
  `up{job="alloy"}`) because a dead log pipeline fails silent — ingestion just
  stops. Alloy buffers and retries while Loki is down; the buffer is finite,
  and `loki_write_dropped_entries_total` on the `alloy` job is the "logs were
  actually lost" signal.
- **Not captured**: logs from real users' browsers. That is GlitchTip's job
  (errors with breadcrumbs via the Sentry SDKs). Do not try to close that gap
  by exposing a Loki push endpoint to browsers — an unauthenticated ingest
  path from the public internet is an abuse surface, not a feature.

### GlitchTip first-run

**There is one supported path: register the admin account in the UI, then run
`./scripts/bootstrap-glitchtip.sh`.** Everything after this list is a *reference
record* of what that script creates and why — kept so the setup stays recoverable
if the script ever stops matching a newer GlitchTip. Do not work through it as a
second procedure. Creating the organization, the projects or the alert rules by
hand *as well* is how you end up with DSNs pointing at one project and alert
rules attached to another, so events arrive somewhere nothing is watching.

1. Set `GLITCHTIP_SECRET_KEY` in `.env` before starting — the container will not
   boot without it:
   ```
   openssl rand -hex 32
   ```
   Fill in the rest of the `GLITCHTIP_*` block from `.env.example` too. For a
   deployed stack: point `GLITCHTIP_DOMAIN` at the real URL, set a real
   `GLITCHTIP_EMAIL_URL` and a matching `GLITCHTIP_FROM_EMAIL`, and set
   `GLITCHTIP_ALERT_EMAIL` to the mailbox that should receive alerts. Leave
   `GLITCHTIP_EMAIL_URL=consolemail://` for local dev — see
   [Alerts](#alerts-making-one-actually-arrive).
2. Start the stack with `--monitoring`. The first boot runs database migrations
   automatically and takes a minute or two.
3. Open the UI at http://localhost:8000 (or `GLITCHTIP_PORT`).
4. Click **Register** and create the first account. This is the admin account, and
   it is the one step the script deliberately does not do: registration sets a
   password, which a bootstrap script has no business holding. With
   `GLITCHTIP_ENABLE_USER_REGISTRATION=False` (the default here), self-signup
   closes as soon as that first account exists — later users must be invited.
5. Run the bootstrap script:
   ```bash
   ./scripts/bootstrap-glitchtip.sh
   ```
   It creates the organization, its team, one project per reporting surface
   (`beyou-backend`, `beyou-web`, `beyou-mobile`), all three monitors, and one
   alert rule per project with an e-mail recipient wired to it. It then prints
   the DSNs, the heartbeat check-in URL, and which address alerts will actually
   reach.

   Safe to run repeatedly, and **not** a no-op on a re-run: creation is
   `get_or_create`, but every run then re-applies the script's own values over
   whatever is in the database, so drift is repaired rather than reported as
   "already present". A second run prints `reconciled …` for anything it had to
   correct. It never creates duplicates — monitors and rules are keyed on name,
   the recipient row on `(rule, type, url)`.

   Two values it reads from `.env`, both of which it overwrites in the collector
   on every run, so a wrong value here beats a right value there:
   ```bash
   GLITCHTIP_FRONTEND_TARGET=frontend:3000   # dev; the script's default is prod's frontend:80
   GLITCHTIP_ALERT_EMAIL=ops@example.com     # empty = the account you registered in step 4
   ```
6. Paste the printed DSNs into the corresponding app env vars, and
   `SNAPSHOT_HEARTBEAT_URL` into this repo's `.env`. A DSN is not a secret in the
   password sense — it is embedded in shipped clients — but keep it out of the
   repo anyway.

Notes:
- Events, logs, and uptime checks are pruned after `GLITCHTIP_RETENTION_DAYS`
  (30 by default) so the event store stays bounded.
- GlitchTip shares `beyou_net` with the backend, so it can reach the management
  port at `http://backend:9091` for uptime checks. Its own Postgres and Valkey
  are isolated on `glitchtip_net`.
- Put GlitchTip behind nginx with SSL for any non-local deployment.

### Alerts: making one actually arrive

Storing errors and turning a monitor red announces nothing. Two GlitchTip code
paths do the announcing, and **both go silent unless an `AlertRecipient` row
exists**:

| Path | Trigger | Requires |
|---|---|---|
| Errors | `apps.alerts.tasks.process_event_alerts`, every 60s | a rule with `quantity` **and** `timespan_minutes` set |
| Uptime + heartbeat | `apps.uptime.tasks.send_monitor_notification`, on state change | a rule on the monitor's project with `uptime = True` |

So the heartbeat monitor — the only thing that can tell you the snapshot
scheduler wedged — needs `uptime = True` on a rule, or it goes red and tells
nobody. The bootstrap script creates **one** rule per project covering both
paths. One and not two on purpose: the uptime lookup joins through the project,
so a second `uptime = True` rule on `beyou-backend` mails every monitor event
twice.

The channel is **e-mail, over the same SMTP the backend already uses** — no new
infrastructure, and that account is known to deliver (it carries the feedback
acknowledgement mail). Compose `GLITCHTIP_EMAIL_URL` from the same `MAIL_*`
credentials; `.env.example` has the exact scheme, the STARTTLS-vs-implicit-TLS
choice, and the three encoding traps that silently break it.

`consolemail://` stays the default so a dev machine does not start mailing.
It is not a stub — the message is fully composed and printed:

```bash
docker logs -f beyou-dev-env-glitchtip-1   # look for "Subject: Error in ..."
```

**The recipient is not the address on the rule.** GlitchTip ignores that field
for e-mail and instead resolves *every user on the team that owns the project*
(`users.UserManager.alert_notification_recipients`). That is why
`GLITCHTIP_ALERT_EMAIL` is applied by the script rather than by Compose: it has
to make the address a user, put it in the organization, and add it to the team.
The script creates it with an unusable password — a mailbox, not a login; use
password-reset if it ever needs the UI. Consequences worth knowing:

- It is **additive**. The account from step 4 keeps receiving alerts. To stop
  that, remove it from the team or set its per-project alerts to Off under
  **Settings → Projects → \<project\> → Alerts**.
- A per-project **Off** beats everything the script does. The script will not
  overwrite that (it is a human's opt-out) but it prints a `WARNING` naming the
  user and projects, because otherwise the rule looks wired and mails nobody.

Reference record — the equivalent by hand, under **Settings → Projects →
\<project\> → Alerts**, for each of the three projects:

| Field | Value |
|---|---|
| Name | `New issue` |
| Send notification when | `1` event in `1` minute |
| Also alert on uptime check failures | yes |
| Recipient | `Email` (no URL — see above) |

Names must match `scripts/bootstrap-glitchtip.py` exactly; the script keys rules
on `(project, name)` and will otherwise create a second one alongside yours.

### Monitors

Three monitors, answering three different questions. The bootstrap script creates
all three — the tables below are the reference record of what it sets and why.
None is created by Compose: GlitchTip monitors live in its database, so a
`GLITCHTIP_RETENTION_DAYS` wipe, a volume reset, or a move to a new host means
re-running the script (not redoing these tables by hand).

If you ever do have to rebuild one manually, it is **Uptime Monitors → New
Monitor**, with the monitor's project set to the one named in its table so alerts
land with that surface's error events — and it still needs the project's alert
rule from [Alerts](#alerts-making-one-actually-arrive) to have `uptime = True`,
or it goes red and tells nobody. A monitor nobody is told about is not a monitor.

> **The names below must match `scripts/bootstrap-glitchtip.py` exactly.** The
> script keys every monitor on its `name` via `get_or_create`. Create one by hand
> under a different name and the next bootstrap run will not recognise it — you
> get two monitors polling the same thing, and the hand-made one has none of the
> `confirmation_threshold` tuning, so it alerts on a single dropped poll.

#### 1. Backend uptime — "is the process answering?"

| Field | Value |
|---|---|
| Name | `Beyou backend health` |
| Project | `beyou-backend` |
| Monitor type | `GET` |
| URL | `http://backend:9091/actuator/health` |
| Expected status | `200` |
| Interval | `60` seconds |
| Timeout | `10` seconds |
| Confirmation threshold | `2` (two consecutive failures — one dropped poll during a restart is not an outage) |

Use the in-network URL, not `localhost` — inside the GlitchTip container
`localhost` is GlitchTip itself. The management server is deliberately not a
public surface: it defaults to binding `127.0.0.1` (`MANAGEMENT_ADDRESS`, which
this stack sets to `0.0.0.0` so the container's port is reachable within
`beyou_net`), and the monitoring overlay only publishes it to the Docker host.
`http://backend:9091` from inside `beyou_net` is therefore the route GlitchTip
has, which is why its web container is dual-homed onto `beyou_net` in
`docker-compose.monitoring.yml`. Verified from inside the collector container:
`http://backend:9091/actuator/health` returns 200 `{"status":"UP"}`.

`GLITCHTIP_UPTIME_ALLOW_PRIVATE_IPS=True` is already set in that file. Without it
GlitchTip's SSRF guard rejects RFC1918 targets and this monitor can never be
saved.

#### 2. Snapshot job heartbeat — "is the scheduled job still running?"

The uptime check above cannot answer this. `RoutineSnapshotScheduler` is what
writes each user's daily routine snapshot, and when its scheduler thread wedges —
or the cron silently stops firing — `/actuator/health` keeps returning 200 while
snapshots quietly stop being written. Nothing fails; data just stops appearing.

So this monitor is inverted: the backend checks in, and GlitchTip alerts on the
check-in **not arriving**.

| Field | Value |
|---|---|
| Name | `Snapshot scheduler heartbeat` |
| Project | `beyou-backend` |
| Monitor type | `Heartbeat` |
| Expected interval | `5400` seconds (90 min) |
| Confirmation threshold | `1` (the interval already carries 30 minutes of slack — do not add more) |

The job runs hourly (`@Scheduled(cron = "0 0 * * * *")`), checking every distinct
user timezone and writing snapshots for those where the local clock just crossed
midnight. It checks in after **every** completed cycle, not only the midnight
ones, so a stalled job is caught within the hour instead of within a day. The
90-minute interval is that hourly cadence plus 30 minutes of slack, so one slow
cycle or a single failed delivery does not page anyone.

Saving the monitor produces an endpoint URL of the form:

```
http://glitchtip:8000/api/0/organizations/<org-slug>/heartbeat_check/<endpoint-id>/
```

Put it in `.env` as `SNAPSHOT_HEARTBEAT_URL` and restart the backend. Use the
in-network host (`glitchtip:8000`) — the backend container resolves that, not
`localhost`. Leaving the variable empty disables the heartbeat entirely and the
backend never attempts an outbound request.

Behaviour worth knowing before you trust the monitor:
- The signal is sent only after a cycle **completes**. A run that throws sends
  nothing, so a broken job shows as a missing heartbeat rather than a green light.
- A failed check-in never fails the snapshot job — it is logged at WARN and the
  cycle carries on. Monitoring must not become the cause of the outage it watches.
- Startup backfill does not check in. Otherwise a backend stuck in a crash-restart
  loop would keep the monitor green forever.
- The `test` and `e2e` profiles pin the URL empty, so test runs can never check in
  on behalf of a job that is not running.

#### 3. Web frontend — "is the app being served at all?"

The two monitors above only ever look at the backend. A healthy API behind a
frontend that stopped being served is still a total outage for every user, and
nothing above would notice it.

| Field | Value |
|---|---|
| Name | `Beyou web frontend` |
| Project | `beyou-web` |
| Monitor type | `TCP Port` |
| URL | `frontend:3000` in dev, `frontend:80` in prod (see below) |
| Interval | `60` seconds |
| Timeout | `10` seconds |
| Confirmation threshold | `2` |

`TCP Port` monitors carry the port inside the URL field — GlitchTip splits that
string on `:` and hands both halves to `asyncio.open_connection`. There is no
separate port input, and `Expected status` is ignored (it is only read by the
HTTP monitor types: GET, POST, PING).

The port differs by environment, and getting it wrong is worse than having no
monitor — it leaves a permanently red light nobody believes. Dev runs Vite
directly on **3000**; prod serves the built assets through nginx on **80**. The
bootstrap script defaults to prod, so a dev run needs the override:

```bash
GLITCHTIP_FRONTEND_TARGET=frontend:3000 ./scripts/bootstrap-glitchtip.sh
```

This is a TCP connect, not an HTTP fetch: it proves something is accepting
connections on that port, not that the app renders or that its JS bundle loads.

### Watching the collector itself

Every alarm described above is raised *by* GlitchTip — the monitors live in its
database, the notifications leave its process, and all three apps POST their
errors to it. So GlitchTip cannot be what tells you GlitchTip is down: when it
wedges, every signal goes quiet at once and the stack looks calm.

Two mechanisms cover that, both in `docker-compose.monitoring.yml`:

- **Compose healthcheck** on the `glitchtip` service, running the image's own
  `/code/healthcheck.py` (`GET /_health/`, exit 0 only on 200). `docker ps` and
  `docker inspect --format '{{.State.Health.Status}}' <container>` then report
  `unhealthy` instead of a misleading `Up`. Allow up to `start_period` (120s) on
  a first boot — migrations run before it starts serving.
- **Prometheus scrape** of `glitchtip:8000/metrics`, as job `glitchtip` in
  `monitoring/prometheus/prometheus.yml`. GlitchTip bundles django-prometheus;
  the endpoint is off by default and is switched on by `ENABLE_OBSERVABILITY_API`
  in the compose file. `up{job="glitchtip"}` is then a liveness signal owned by
  the one component that is *not* the collector. No extra exporter is involved.

> **Both of these are still look-at-it signals.** Everything GlitchTip watches
> now announces itself by e-mail (see
> [Alerts](#alerts-making-one-actually-arrive)), but *collector death* does not:
> Prometheus scrapes `up{job="glitchtip"}` and nothing evaluates it, and the
> Compose healthcheck only changes what `docker ps` prints. So a wedged collector
> still has to be noticed rather than reported.
>
> That gap is deliberate, not an oversight. GlitchTip cannot be the thing that
> announces GlitchTip is down, and closing it properly means either an
> alertmanager (`alerting:` + `rule_files:` in
> `monitoring/prometheus/prometheus.yml`, with `up{job="glitchtip"} == 0` as the
> first rule) or Grafana's own alerting — a second notification system to own,
> which was consciously not introduced alongside the first. Until then, treat
> "GlitchTip has gone quiet" as a thing to check, not a thing to trust.

## Ports
- Frontend: 3000
- Backend: 8099
- Postgres: 5490
- Prometheus: 9090
- Grafana: 3001
- GlitchTip: 8000
- Alloy (debug UI): 12345
- Loki: no host port on purpose — query it through Grafana
