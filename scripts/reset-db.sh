#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root_dir"

# Docker Compose lowercases the project name, so the volume is
# `beyou-dev-env_postgres_data`, not the raw (capitalized) basename. Getting this
# wrong silently no-ops the reset (the bug this replaces), so we fail loudly below
# instead of printing "complete" when nothing was removed.
project_name="${COMPOSE_PROJECT_NAME:-$(basename "$root_dir")}"
project_name="$(printf '%s' "$project_name" | tr '[:upper:]' '[:lower:]')"
volume="${project_name}_postgres_data"

# Tear down with the same file set up-dev.sh uses, so the container holding the
# volume is actually stopped before we try to remove it.
docker compose -f docker-compose.yml -f docker-compose.dev.yml down --remove-orphans

if ! docker volume inspect "$volume" >/dev/null 2>&1; then
    echo "reset-db: volume '$volume' not found — nothing removed." >&2
    echo "reset-db: existing postgres_data volumes:" >&2
    docker volume ls --format '{{.Name}}' | grep postgres_data >&2 || echo "  (none)" >&2
    echo "reset-db: set COMPOSE_PROJECT_NAME if your project name differs." >&2
    exit 1
fi

docker volume rm "$volume"
printf 'Postgres volume reset complete (%s).\n' "$volume"
