#!/usr/bin/env bash
set -euo pipefail

mode="${1:-dev}"
root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root_dir"

MONITORING=false
for arg in "$@"; do
  case "$arg" in
    --monitoring) MONITORING=true ;;
  esac
done

compose_args=("-f" "docker-compose.yml")
if [[ "$mode" == "dev" ]]; then
  compose_args+=("-f" "docker-compose.dev.yml")
elif [[ "$mode" == "prod" ]]; then
  compose_args+=("-f" "docker-compose.prod.yml")
else
  echo "Unknown mode: $mode (use dev or prod)" >&2
  exit 1
fi

if [[ "$MONITORING" == true ]]; then
  compose_args+=("-f" "docker-compose.monitoring.yml")
fi

docker compose "${compose_args[@]}" down --remove-orphans
