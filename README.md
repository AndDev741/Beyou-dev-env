# Beyou Dev Environment

This repo orchestrates the Beyou backend, frontend, and Postgres for local development and a production-like run using Docker Compose.

## Prerequisites
- Docker Desktop or Docker Engine with `docker compose`

## Layout
Clone all the required repositories in a single folder

```bash
git clone https://github.com/andre/beyou-backend
git clone https://github.com/andre/beyou-frontend
git clone https://github.com/andre/beyou-dev-env
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

## Ports
- Frontend: 3000
- Backend: 8099
- Postgres: 5490
