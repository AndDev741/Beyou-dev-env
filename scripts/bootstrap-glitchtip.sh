#!/usr/bin/env bash
set -euo pipefail

# Creates the GlitchTip organization, projects, monitors and alert rules, then
# prints the values a deployment has to configure. Safe to run repeatedly, and
# NOT a no-op on a re-run: it re-applies its own values over anything that
# drifted in the collector. See scripts/bootstrap-glitchtip.py.
#
# Prerequisite: the first GlitchTip account must already exist. Registration is
# a UI step because it sets a password, and a bootstrap script has no business
# holding one.
#
# Usage:
#   ./scripts/bootstrap-glitchtip.sh
#   GLITCHTIP_FRONTEND_TARGET=frontend:3000 ./scripts/bootstrap-glitchtip.sh   # dev

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root_dir"

# Read .env so the GLITCHTIP_*_TARGET variables and GLITCHTIP_ALERT_EMAIL have
# a persistent home rather than needing a manual prefix every run — forgetting
# a target lets reconcile() rewrite a correct dev override back to the
# production default, and forgetting the email silently re-points alerts at
# the first registered account.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

container="$(docker ps --filter "name=glitchtip-1" --filter "status=running" --format '{{.Names}}' | head -1)"

if [ -z "$container" ]; then
  echo "GlitchTip is not running. Start the monitoring stack first:" >&2
  echo "  ./scripts/up-dev.sh --monitoring" >&2
  exit 1
fi

# The Python reads these from *its* environment, which is the container's —
# `docker exec` does not inherit the caller's shell. Without this forwarding the
# documented dev override was silently a no-op, and worse: the script's
# reconcile() then rewrote a correct frontend:3000 back to the frontend:80
# default on every run, leaving the monitor permanently DOWN in dev.
#
# Forwarded only when actually set, so an unset variable still falls through to
# the Python default rather than arriving as an empty string.
exec_args=(-i)
for var in \
  GLITCHTIP_FRONTEND_TARGET GLITCHTIP_BACKEND_TARGET GLITCHTIP_DB_TARGET \
  GLITCHTIP_GLITCHTIP_DB_TARGET GLITCHTIP_VALKEY_TARGET \
  GLITCHTIP_WATCHTOWER_TARGET GLITCHTIP_LOKI_TARGET GLITCHTIP_ALLOY_TARGET \
  GLITCHTIP_PROMETHEUS_TARGET GLITCHTIP_GRAFANA_TARGET \
  GLITCHTIP_GLITCHTIP_TARGET GLITCHTIP_ALERT_EMAIL; do
  if [ -n "${!var:-}" ]; then
    exec_args+=(-e "$var=${!var}")
  fi
done

# Piped through stdin rather than `shell -c`: the script is long and quoting it
# through docker exec, sh and Python mangles it.
docker exec "${exec_args[@]}" "$container" ./manage.py shell \
  < "$root_dir/scripts/bootstrap-glitchtip.py" 2>&1 \
  | grep -vE "objects imported automatically|RuntimeWarning|return _bootstrap"
