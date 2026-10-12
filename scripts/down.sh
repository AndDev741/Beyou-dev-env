#!/usr/bin/env bash
set -euo pipefail

# Stops the local dev stack. Usage: down.sh [dev] [--monitoring]
# "dev" is the only mode (production runs on Kubernetes from be-infra); it is
# still accepted so existing muscle memory and docs keep working.

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root_dir"

MONITORING=false
for arg in "$@"; do
  case "$arg" in
    dev) ;;
    --monitoring) MONITORING=true ;;
    *)
      echo "Unknown argument: $arg (usage: down.sh [dev] [--monitoring])" >&2
      exit 1
      ;;
  esac
done

compose_args=("-f" "docker-compose.yml" "-f" "docker-compose.dev.yml")

if [[ "$MONITORING" == true ]]; then
  compose_args+=("-f" "docker-compose.monitoring.yml")
fi

docker compose "${compose_args[@]}" down --remove-orphans
