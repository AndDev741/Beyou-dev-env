#!/usr/bin/env bash
# Nightly offsite backup: app Postgres + uploads + .env -> restic repo on Cloudflare R2,
# with a plain-file local copy kept for fast restores.
#
# WHAT IS AND IS NOT IN HERE
#   in:  the `beyou` database, the beyou_uploads volume, and .env — the three things on this
#        box that exist nowhere else. .env is the highest-value item by a wide margin: it is
#        gitignored, so TOKEN_SECRET, the Google OAuth secret, the mail password,
#        DOCS_IMPORT_TOKEN and every LLM API key live in exactly one place until this runs.
#   weekly: the GlitchTip database. Bigger than the app DB and mostly replaceable event
#        history, but its bootstrap-issued DSNs are referenced from .env, so re-bootstrapping
#        after a loss is not free.
#   out: Loki (bounded, replaceable logs), Grafana's volume (dashboards are provisioned from
#        this repo, read-only), code and images (git + GHCR).
#
# Every artefact is produced by streaming a container's stdout to a host file. No bind mount
# into a container, so nothing here ever writes a root-owned file into the staging tree.
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root_dir"

log() { printf '%s backup: %s\n' "$(date -Is)" "$*"; }
die() { printf '%s backup: FATAL %s\n' "$(date -Is)" "$*" >&2; exit 1; }

# Only one run at a time. A nightly job that overlaps a slow predecessor produces two restic
# writers against one repo and a half-written dump in the local copy.
exec 9>"${BACKUP_LOCK:-/var/lock/beyou-backup.lock}"
flock -n 9 || die "another backup run holds the lock; giving up"

[[ -f .env ]] || die ".env not found in $root_dir"
# shellcheck disable=SC1091
set -a; source .env; set +a

: "${RESTIC_REPOSITORY:?Must set RESTIC_REPOSITORY in .env}"
: "${RESTIC_PASSWORD_FILE:?Must set RESTIC_PASSWORD_FILE in .env}"
: "${AWS_ACCESS_KEY_ID:?Must set AWS_ACCESS_KEY_ID in .env (R2 token id)}"
: "${AWS_SECRET_ACCESS_KEY:?Must set AWS_SECRET_ACCESS_KEY in .env (R2 token secret)}"
export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY

[[ -r "$RESTIC_PASSWORD_FILE" ]] || die "cannot read RESTIC_PASSWORD_FILE ($RESTIC_PASSWORD_FILE)"

db_name="${POSTGRES_DB:-beyou}"
db_user="${POSTGRES_USER:-postgres}"
local_dir="${BACKUP_LOCAL_DIR:-/var/backups/beyou}"
local_keep_days="${BACKUP_LOCAL_KEEP_DAYS:-7}"

# Compose lowercases the project name, same trap reset-db.sh documents.
project_name="${COMPOSE_PROJECT_NAME:-$(basename "$root_dir")}"
project_name="$(printf '%s' "$project_name" | tr '[:upper:]' '[:lower:]')"

# Resolve containers by compose label, not by name. `docker compose ps` would need the exact
# overlay list (which differs between --monitoring and not) and hardcoded
# `beyou-dev-env-db-1` breaks the day the project directory is renamed.
container_for() {
  docker ps -q \
    --filter "label=com.docker.compose.project=${project_name}" \
    --filter "label=com.docker.compose.service=$1" | head -n1
}

db_cid="$(container_for db)"
[[ -n "$db_cid" ]] || die "no running 'db' container for compose project '${project_name}'"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"

# The staging path is STABLE, not mktemp. Two reasons, and the first one is a silent
# data-retention bug:
#
#  1. `restic forget` groups snapshots by host+paths by default. A fresh mktemp path every
#     night puts every snapshot in a group of its own, so "--keep-daily 7" keeps 1 of 1 in
#     each group, forever — nothing is ever pruned and the repository grows without bound.
#     Verified: two runs minutes apart both survived a --keep-daily 7 forget. `--group-by
#     host` below is the belt to this braces.
#  2. A stable path lets restic find the previous snapshot as a parent, so nightly runs are
#     genuinely incremental instead of re-reading everything.
#
# Wiped on the way IN as well as out: a crashed previous run could otherwise leave a stale
# dump here that the next run would quietly ship as if it were current.
# Deliberately NOT under $local_dir: the retention prune and restore-check --local
# both enumerate that directory, and a staging dir sitting in it would be treated as
# a dated copy ('staging' sorts after '2026...', so --local would restore it).
staging="${BACKUP_STAGING_DIR:-/var/backups/beyou-staging}"
rm -rf "$staging"
mkdir -p "$staging" || die "cannot create staging dir $staging"
chmod 700 "$staging"   # .env lands in here in cleartext until restic encrypts it
trap 'rm -rf "$staging"' EXIT

log "staging in $staging (project=${project_name}, db=${db_name})"

# --- 1. Database ---------------------------------------------------------------------------
# pg_dump runs INSIDE the container so the client version always matches the server. Never
# tar /var/lib/postgresql/data from a running instance: that is a torn copy which may refuse
# to restore, and you find out on the day you need it.
log "dumping database ${db_name}"
docker exec -e PGPASSWORD="${POSTGRES_PASSWORD:-}" "$db_cid" \
  pg_dump -Fc -U "$db_user" -d "$db_name" > "$staging/${db_name}.dump"
[[ -s "$staging/${db_name}.dump" ]] || die "database dump is empty"

# --- 2. Uploads ---------------------------------------------------------------------------
# ORDER IS DELIBERATE: uploads are captured AFTER the database dump. Upload paths are UUIDs
# and are only ever added, so a file written between the two steps becomes a harmless orphan
# in the archive. Reverse the order and you get the bad case instead — a restored row
# pointing at a file that was never copied, i.e. a silent broken reference.
log "archiving uploads volume"
docker run --rm -v "${project_name}_beyou_uploads:/src:ro" alpine \
  tar -czf - -C /src . > "$staging/uploads.tar.gz"

# --- 3. Secrets ---------------------------------------------------------------------------
cp .env "$staging/env"

# --- 4. GlitchTip, weekly ----------------------------------------------------------------
if [[ "$(date -u +%u)" == "7" || "${BACKUP_INCLUDE_GLITCHTIP:-}" == "true" ]]; then
  gt_cid="$(container_for glitchtip-db)"
  if [[ -n "$gt_cid" ]]; then
    log "weekly: dumping glitchtip database"
    docker exec -e PGPASSWORD="${GLITCHTIP_DB_PASSWORD:-}" "$gt_cid" \
      pg_dump -Fc -U "${GLITCHTIP_DB_USER:-glitchtip}" \
      -d "${GLITCHTIP_DB_NAME:-glitchtip}" > "$staging/glitchtip.dump" \
      || log "WARN glitchtip dump failed; continuing (app data is what matters)"
  else
    log "weekly: no glitchtip-db container running, skipping"
  fi
fi

printf 'stamp=%s\nhost=%s\nproject=%s\ndb=%s\n' \
  "$stamp" "$(hostname)" "$project_name" "$db_name" > "$staging/MANIFEST"

# --- 5. Local copy ------------------------------------------------------------------------
# The fast path. Most restores are "someone deleted the wrong thing an hour ago", which
# should not require a network round trip or a restic password.
if mkdir -p "$local_dir" 2>/dev/null; then
  cp -a "$staging" "$local_dir/$stamp" && chmod 700 "$local_dir/$stamp"
  # -name '2*' so only stamped copies are ever candidates for deletion. A bare
  # -type d here would happily delete anything else that appears in this directory.
  find "$local_dir" -maxdepth 1 -mindepth 1 -type d -name '2*' -mtime "+${local_keep_days}" \
    -exec rm -rf {} + 2>/dev/null || true
  log "local copy at $local_dir/$stamp"
else
  log "WARN could not write local copy to $local_dir; offsite copy still proceeding"
fi

# --- 6. Offsite ---------------------------------------------------------------------------
# restic encrypts client-side, which is what makes it acceptable to ship .env and a full user
# database to third-party storage at all.
log "uploading to $RESTIC_REPOSITORY"
restic snapshots >/dev/null 2>&1 || { log "initialising restic repository"; restic init; }

restic backup \
  --tag beyou --tag "stamp=$stamp" \
  --host "$(hostname)" \
  "$staging"

log "applying retention (7 daily / 4 weekly / 6 monthly)"
# --group-by host (NOT the default host,paths, and not tags — the stamp tag is unique per
# run, so grouping by tags would recreate the exact same one-snapshot-per-group bug).
restic forget --tag beyou --prune --group-by host \
  --keep-daily 7 --keep-weekly 4 --keep-monthly 6

# --- 7. Size guard ------------------------------------------------------------------------
# Cloudflare has NO hard spend cap. Budget alerts are explicitly informational ("does not cap
# your usage or impact your account in any way") and they fire a day late, because usage is
# processed once daily. So the only thing that can actually stop this bucket from costing
# money is this script.
#
# R2's free tier is 10 GB-month. Measured steady state for this stack is ~0.2 GB (17 retained
# snapshots of a ~11 MB payload), i.e. about 2% of the allowance, so the guard sits far above
# normal and only trips on something genuinely wrong: a table that started storing blobs, an
# uploads directory that ran away, or a retention policy that quietly stopped pruning.
#
# It runs AFTER forget --prune, so it measures what is actually retained rather than the peak
# mid-run. On a trip it deliberately skips the heartbeat and exits non-zero: the backup itself
# already succeeded, but staying silent until the invoice arrives is the failure being
# prevented.
#
# Do NOT solve a size problem with an R2 lifecycle rule that expires objects. restic's pack
# files are referenced by snapshots it still believes are intact; deleting them out from under
# it corrupts the repository, and you find out at restore time. Lower the retention policy or
# BACKUP_MAX_REPO_GB instead.
max_gb="${BACKUP_MAX_REPO_GB:-5}"
repo_bytes="$(restic stats --mode raw-data --json 2>/dev/null \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["total_size"])' 2>/dev/null || echo 0)"
if [[ "$repo_bytes" -gt 0 ]]; then
  repo_mb=$(( repo_bytes / 1024 / 1024 ))
  max_mb=$(( max_gb * 1024 ))
  log "repository size ${repo_mb} MiB (guard ${max_gb} GiB, R2 free tier 10 GB)"
  if [[ "$repo_mb" -gt "$max_mb" ]]; then
    log "ERROR repository is ${repo_mb} MiB, over the ${max_gb} GiB guard."
    log "ERROR the backup SUCCEEDED; this is a cost alarm, not a backup failure."
    log "ERROR investigate what grew, then lower retention or raise BACKUP_MAX_REPO_GB."
    exit 1
  fi
else
  log "WARN could not read repository size; skipping the cost guard this run"
fi

# --- 8. Heartbeat -------------------------------------------------------------------------
# Success only. A backup that stops running is the standard failure mode and it is invisible
# from the inside, so the alert has to come from the ABSENCE of this ping — same inverted
# check as the RoutineSnapshotScheduler monitor in the README.
if [[ -n "${BACKUP_HEARTBEAT_URL:-}" ]]; then
  curl -fsS -m 10 -X POST "$BACKUP_HEARTBEAT_URL" >/dev/null \
    && log "heartbeat sent" \
    || log "WARN heartbeat failed; the backup itself succeeded"
fi

log "done"
