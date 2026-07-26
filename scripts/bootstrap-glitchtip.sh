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

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root_dir"

container="$(docker ps --filter "name=glitchtip-1" --filter "status=running" --format '{{.Names}}' | head -1)"

if [ -z "$container" ]; then
  echo "GlitchTip is not running. Start the monitoring stack first:" >&2
  echo "  ./scripts/up-dev.sh --monitoring" >&2
  exit 1
fi

# Piped through stdin rather than `shell -c`: the script is long and quoting it
# through docker exec, sh and Python mangles it.
docker exec -i "$container" ./manage.py shell \
  < "$root_dir/scripts/bootstrap-glitchtip.py" 2>&1 \
  | grep -vE "objects imported automatically|RuntimeWarning|return _bootstrap"
