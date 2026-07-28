#!/usr/bin/env bash
set -euo pipefail

# Creates the GlitchTip organization, projects and monitors, then prints the
# values a deployment has to configure. Safe to run repeatedly — every step is
# get_or_create.
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

container="$(docker ps --filter "name=glitchtip-1" --filter "status=running" --format '{{.Names}}' | head -1)"

if [ -z "$container" ]; then
  echo "GlitchTip is not running. Start the monitoring stack first:" >&2
  echo "  ./scripts/up-dev.sh --monitoring" >&2
  exit 1
fi

# The Python reads GLITCHTIP_FRONTEND_TARGET from *its* environment, which is the
# container's — `docker exec` does not inherit the caller's shell. Without this
# forwarding the documented dev override was silently a no-op, and worse: the
# script's reconcile() then rewrote a correct frontend:3000 back to the
# frontend:80 default on every run, leaving the monitor permanently DOWN in dev.
#
# Forwarded only when actually set, so an unset variable still falls through to
# the Python default rather than arriving as an empty string.
exec_args=(-i)
if [ -n "${GLITCHTIP_FRONTEND_TARGET:-}" ]; then
  exec_args+=(-e "GLITCHTIP_FRONTEND_TARGET=$GLITCHTIP_FRONTEND_TARGET")
fi

# Piped through stdin rather than `shell -c`: the script is long and quoting it
# through docker exec, sh and Python mangles it.
docker exec "${exec_args[@]}" "$container" ./manage.py shell \
  < "$root_dir/scripts/bootstrap-glitchtip.py" 2>&1 \
  | grep -vE "objects imported automatically|RuntimeWarning|return _bootstrap"
