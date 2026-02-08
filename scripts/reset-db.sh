#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root_dir"

project_name="${COMPOSE_PROJECT_NAME:-$(basename "$root_dir")}"

# Stop db and remove only the Postgres volume

docker compose -f docker-compose.yml down --remove-orphans

docker volume rm "${project_name}_postgres_data" 2>/dev/null || true

printf 'Postgres volume reset complete.\n'
