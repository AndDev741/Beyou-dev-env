#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root_dir"

# Mirrors up-dev.sh. The overlay is no longer optional decoration — error
# reporting and both uptime monitors live in it, and `down.sh prod --monitoring`
# already accepted a flag for a stack this script could never start.
MONITORING=false
for arg in "$@"; do
  case "$arg" in
    --monitoring) MONITORING=true ;;
  esac
done

compose_args=("-f" "docker-compose.yml" "-f" "docker-compose.prod.yml")

if [[ "$MONITORING" == true ]]; then
  compose_args+=("-f" "docker-compose.monitoring.yml")
fi

docker compose "${compose_args[@]}" pull
docker compose "${compose_args[@]}" up -d
