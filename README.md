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
Grafana, and GlitchTip (self-hosted error telemetry, Sentry-API compatible).

```
./scripts/up-dev.sh --monitoring
./scripts/down.sh dev --monitoring
```

### GlitchTip first-run

1. Set `GLITCHTIP_SECRET_KEY` in `.env` before starting — the container will not
   boot without it:
   ```
   openssl rand -hex 32
   ```
   Fill in the rest of the `GLITCHTIP_*` block in `.env.example` too. For a
   deployed stack, point `GLITCHTIP_DOMAIN` at the real URL and set a real
   `GLITCHTIP_EMAIL_URL`, otherwise new-issue alerts only reach the container log.
2. Start the stack with `--monitoring`. The first boot runs database migrations
   automatically and takes a minute or two.
3. Open the UI at http://localhost:8000 (or `GLITCHTIP_PORT`).
4. Click **Register** and create the first account. This is the admin account.
   With `GLITCHTIP_ENABLE_USER_REGISTRATION=False` (the default here), self-signup
   closes as soon as that first account exists — later users must be invited.
5. Create an organization, then a project — one project per surface
   (`beyou-backend`, `beyou-web`, `beyou-mobile`).
6. The project's DSN is under **Settings → Projects → \<project\> → Client Keys (DSN)**.
   Copy it into the corresponding app's env var. The DSN is not a secret in the
   password sense — it is embedded in shipped clients — but keep it out of the
   repo anyway.

Notes:
- Events, logs, and uptime checks are pruned after `GLITCHTIP_RETENTION_DAYS`
  (30 by default) so the event store stays bounded.
- GlitchTip shares `beyou_net` with the backend, so it can reach the management
  port at `http://backend:9091` for uptime checks. Its own Postgres and Valkey
  are isolated on `glitchtip_net`.
- Put GlitchTip behind nginx with SSL for any non-local deployment.

### Bootstrap script (do this instead of the manual steps below)

```bash
./scripts/bootstrap-glitchtip.sh
```

Creates the organization, one project per reporting surface, and both monitors,
then prints the DSNs and the heartbeat check-in URL ready to paste into the three
`.env` files. Safe to run repeatedly — every step is get_or_create, so a second
run reports "already present" and changes nothing.

It does **not** create the first account: registration sets a password, which a
script has no business holding. Register in the UI first, then run this.

The sections below document what the script creates and why, so the setup stays
recoverable if the script ever stops matching a newer GlitchTip.

### Monitors

Two monitors, answering two different questions. Neither is created by Compose —
GlitchTip monitors live in its database, created through the UI or its API — so
recreating them after a `GLITCHTIP_RETENTION_DAYS` wipe, a volume reset, or a move
to a new host means redoing these steps.

Both live under **Uptime Monitors → New Monitor** in the GlitchTip UI. Set the
project to `beyou-backend` so the alerts land with the backend's error events, and
attach a notification target (**Settings → Organization → Alerts**) — a monitor
nobody is told about is not a monitor.

#### 1. Backend uptime — "is the process answering?"

| Field | Value |
|---|---|
| Name | `beyou-backend health` |
| Monitor type | `GET` |
| URL | `http://backend:9091/actuator/health` |
| Expected status | `200` |
| Interval | `60` seconds |
| Timeout | `10` seconds |

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
| Name | `beyou-backend snapshot job` |
| Monitor type | `Heartbeat` |
| Expected interval | `5400` seconds (90 min) |

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

## Ports
- Frontend: 3000
- Backend: 8099
- Postgres: 5490
- Prometheus: 9090
- Grafana: 3001
- GlitchTip: 8000
