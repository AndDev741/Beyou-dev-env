#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root_dir"

MONITORING=false
for arg in "$@"; do
  case "$arg" in
    --monitoring) MONITORING=true ;;
  esac
done

compose_args=("-f" "docker-compose.yml" "-f" "docker-compose.dev.yml")

if [[ "$MONITORING" == true ]]; then
  compose_args+=("-f" "docker-compose.monitoring.yml")
fi

docker compose "${compose_args[@]}" up --build
