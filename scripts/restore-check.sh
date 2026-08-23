#!/usr/bin/env bash
# Restore drill. Pulls the newest snapshot, restores the app database into a THROWAWAY
# database, and compares row counts against the live one.
#
# This script is the point of the whole exercise. An untested backup is not a backup — it is
# a directory that makes you feel better. Run it on a schedule (restore-check.timer, weekly),
# not just when you are worried.
#
#   scripts/restore-check.sh              # newest snapshot from R2
#   scripts/restore-check.sh --local       # newest local copy, no network, no restic password
#   scripts/restore-check.sh <snapshot-id> # a specific restic snapshot
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root_dir"

log() { printf '%s restore-check: %s\n' "$(date -Is)" "$*"; }
die() { printf '%s restore-check: FATAL %s\n' "$(date -Is)" "$*" >&2; exit 1; }

[[ -f .env ]] || die ".env not found in $root_dir"
# shellcheck disable=SC1091
set -a; source .env; set +a

source_mode=restic
snapshot=latest
for arg in "$@"; do
  case "$arg" in
    --local) source_mode=local ;;
    *)       snapshot="$arg" ;;
  esac
done

db_name="${POSTGRES_DB:-beyou}"
db_user="${POSTGRES_USER:-postgres}"
local_dir="${BACKUP_LOCAL_DIR:-/var/backups/beyou}"

# The scratch database name is asserted, not assumed. Everything below runs pg_restore and a
# DROP DATABASE, and the one unrecoverable mistake this script could make is pointing either
# at the live database. A name that does not contain "restorecheck" stops the run.
scratch="${db_name}_restorecheck"
[[ "$scratch" == *restorecheck* ]] || die "refusing to touch '$scratch': not a scratch name"
[[ "$scratch" != "$db_name" ]]    || die "scratch name collides with the live database"

project_name="${COMPOSE_PROJECT_NAME:-$(basename "$root_dir")}"
project_name="$(printf '%s' "$project_name" | tr '[:upper:]' '[:lower:]')"
db_cid="$(docker ps -q \
  --filter "label=com.docker.compose.project=${project_name}" \
  --filter "label=com.docker.compose.service=db" | head -n1)"
[[ -n "$db_cid" ]] || die "no running 'db' container for compose project '${project_name}'"

work="$(mktemp -d "${TMPDIR:-/tmp}/beyou-restorecheck.XXXXXX")"
chmod 700 "$work"
trap 'rm -rf "$work"' EXIT

if [[ "$source_mode" == local ]]; then
  # -name '2*' restricts this to stamped copies. The stamps are UTC ISO-basic, so a
  # lexical sort is a chronological sort.
  newest="$(find "$local_dir" -maxdepth 1 -mindepth 1 -type d -name '2*' | sort | tail -n1)"
  [[ -n "$newest" ]] || die "no local copies under $local_dir"
  log "using local copy $newest"
  cp "$newest/${db_name}.dump" "$work/db.dump"
else
  : "${RESTIC_REPOSITORY:?Must set RESTIC_REPOSITORY in .env}"
  : "${RESTIC_PASSWORD_FILE:?Must set RESTIC_PASSWORD_FILE in .env}"
  export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
  log "restoring snapshot '$snapshot' from $RESTIC_REPOSITORY"
  restic restore "$snapshot" --target "$work/r" --include "*/${db_name}.dump"
  found="$(find "$work/r" -name "${db_name}.dump" | head -n1)"
  [[ -n "$found" ]] || die "snapshot contained no ${db_name}.dump"
  mv "$found" "$work/db.dump"
fi

size=$(stat -c%s "$work/db.dump")
[[ "$size" -gt 0 ]] || die "restored dump is empty"
log "dump retrieved ($size bytes)"

psql_root() { docker exec -i -e PGPASSWORD="${POSTGRES_PASSWORD:-}" "$db_cid" psql -U "$db_user" -d postgres "$@"; }

log "recreating scratch database $scratch"
psql_root -qtAc "DROP DATABASE IF EXISTS \"$scratch\";" >/dev/null
psql_root -qtAc "CREATE DATABASE \"$scratch\";" >/dev/null

log "restoring into $scratch"
docker exec -i -e PGPASSWORD="${POSTGRES_PASSWORD:-}" "$db_cid" \
  pg_restore --no-owner --no-privileges -U "$db_user" -d "$scratch" < "$work/db.dump" \
  || log "WARN pg_restore reported errors; row comparison below is the real verdict"

# Compare every public table's row count, live vs restored. Counts are allowed to drift
# upward on the live side (rows written since the dump); a restored table that is EMPTY while
# live has rows, or a table missing entirely, is a failure.
count_sql="SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY relname;"
q() { docker exec -e PGPASSWORD="${POSTGRES_PASSWORD:-}" "$db_cid" psql -U "$db_user" -d "$1" -qtAF: -c "$2"; }

# n_live_tup is an estimate refreshed by ANALYZE, so analyze both before reading it.
docker exec -e PGPASSWORD="${POSTGRES_PASSWORD:-}" "$db_cid" psql -U "$db_user" -d "$scratch" -qc "ANALYZE;" >/dev/null
docker exec -e PGPASSWORD="${POSTGRES_PASSWORD:-}" "$db_cid" psql -U "$db_user" -d "$db_name" -qc "ANALYZE;" >/dev/null

q "$db_name" "$count_sql" | sort > "$work/live.txt"
q "$scratch" "$count_sql" | sort > "$work/restored.txt"

live_tables=$(wc -l < "$work/live.txt")
rest_tables=$(wc -l < "$work/restored.txt")
log "tables: live=$live_tables restored=$rest_tables"

failures=0
while IFS=: read -r table live_rows; do
  [[ -n "$table" ]] || continue
  rest_rows="$(awk -F: -v t="$table" '$1==t{print $2}' "$work/restored.txt")"
  if [[ -z "$rest_rows" ]]; then
    printf '  MISSING  %-40s live=%s restored=(absent)\n' "$table" "$live_rows"
    failures=$((failures+1))
  elif [[ "$live_rows" -gt 0 && "$rest_rows" -eq 0 ]]; then
    printf '  EMPTY    %-40s live=%s restored=0\n' "$table" "$live_rows"
    failures=$((failures+1))
  else
    printf '  ok       %-40s live=%s restored=%s\n' "$table" "$live_rows" "$rest_rows"
  fi
done < "$work/live.txt"

log "dropping scratch database"
psql_root -qtAc "DROP DATABASE IF EXISTS \"$scratch\";" >/dev/null

if [[ "$failures" -gt 0 ]]; then
  die "$failures table(s) failed the restore drill — THE BACKUP IS NOT TRUSTWORTHY"
fi

log "PASS — restore verified against $live_tables tables"
if [[ -n "${BACKUP_RESTORE_HEARTBEAT_URL:-}" ]]; then
  curl -fsS -m 10 -X POST "$BACKUP_RESTORE_HEARTBEAT_URL" >/dev/null \
    && log "heartbeat sent" || log "WARN heartbeat failed; the drill itself passed"
fi
