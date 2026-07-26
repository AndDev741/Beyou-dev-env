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

## Ports
- Frontend: 3000
- Backend: 8099
- Postgres: 5490
- Prometheus: 9090
- Grafana: 3001
- GlitchTip: 8000
