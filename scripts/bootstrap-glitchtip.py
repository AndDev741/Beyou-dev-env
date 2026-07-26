# Idempotent GlitchTip bootstrap. Piped into `manage.py shell` by
# scripts/bootstrap-glitchtip.sh — see that script for why, and run it rather
# than this file directly.
#
# Creates, only when missing: the organization, its team, one project per
# reporting surface, and the two monitors. Then prints the DSNs and the
# heartbeat check-in URL, which are the values a deployment has to configure.
#
# Every step is get_or_create, so running this twice changes nothing. It never
# creates a user: register the first account in the UI, which sets a password
# this script has no business knowing.

from django.apps import apps

Organization = apps.get_model("organizations_ext", "Organization")
Team = apps.get_model("teams", "Team")
Project = apps.get_model("projects", "Project")
ProjectKey = apps.get_model("projects", "ProjectKey")
Monitor = apps.get_model("uptime", "Monitor")
User = apps.get_model("users", "User")

ORG_SLUG = "beyou"
TEAM_SLUG = "beyou-dev"

# One project per surface. Errors from three different runtimes group, alert and
# resolve independently, and source maps upload per project — a single shared
# project makes all three worse.
SURFACES = [
    ("beyou-backend", "Beyou Backend", "java-spring-boot"),
    ("beyou-web", "Beyou Web", "javascript-react"),
    ("beyou-mobile", "Beyou Mobile", "react-native"),
]

# The management port is bound to 127.0.0.1, so only a monitor sharing the
# compose network can reach it. That is why GlitchTip lives in the monitoring
# overlay rather than on its own host.
UPTIME_URL = "http://backend:9091/actuator/health"

# The snapshot job runs hourly on the hour. 90 minutes leaves room for one slow
# cycle or a single failed check-in without paging anyone.
HEARTBEAT_PERIOD_SECONDS = 5400

owner = User.objects.order_by("id").first()
if owner is None:
    print("BOOTSTRAP-ERROR: no GlitchTip user exists yet.")
    print("Register the first account in the UI, then run this again.")
    raise SystemExit(1)

org, created = Organization.objects.get_or_create(slug=ORG_SLUG, defaults={"name": "Beyou"})
print(f"organization {org.slug}: {'created' if created else 'already present'}")

team = Team.objects.filter(organization=org).order_by("id").first()
if team is None:
    team = Team.objects.create(organization=org, slug=TEAM_SLUG)
    print(f"team {team.slug}: created")
else:
    print(f"team {team.slug}: already present")

dsns = {}
for slug, name, platform in SURFACES:
    project, created = Project.objects.get_or_create(
        slug=slug,
        organization=org,
        defaults={"name": name, "platform": platform},
    )
    project.teams.add(team)
    # A post-save signal issues the key, so this normally finds rather than creates.
    key, _ = ProjectKey.objects.get_or_create(project=project)
    dsns[slug] = (key.public_key, project.id)
    print(f"project {slug}: {'created' if created else 'already present'}")

backend_project = Project.objects.get(slug="beyou-backend", organization=org)

uptime, created = Monitor.objects.get_or_create(
    name="Beyou backend health",
    organization=org,
    defaults={
        "project": backend_project,
        "monitor_type": "GET",
        "url": UPTIME_URL,
        "expected_status": 200,
        "interval": 60,
        "timeout": 10,
        # Two consecutive failures before alerting: one dropped poll during a
        # restart is not an outage.
        "confirmation_threshold": 2,
    },
)
print(f"monitor 'Beyou backend health': {'created' if created else 'already present'}")

heartbeat, created = Monitor.objects.get_or_create(
    name="Snapshot scheduler heartbeat",
    organization=org,
    defaults={
        "project": backend_project,
        "monitor_type": "Heartbeat",
        "interval": HEARTBEAT_PERIOD_SECONDS,
        "confirmation_threshold": 1,
    },
)
print(f"monitor 'Snapshot scheduler heartbeat': {'created' if created else 'already present'}")

def dsn_key(public_key):
    """GlitchTip issues hyphenated UUID keys. The JavaScript SDK's DSN parser
    matches the public key with `\\w+`, which excludes `-`, so a hyphenated key
    makes makeDsn() fail — no transport is constructed and every event is
    dropped in silence, with no error anywhere. GlitchTip's ingest accepts the
    key with the hyphens removed, so strip them. The Java SDK parses either
    form; stripping everywhere keeps one rule instead of a per-surface one
    somebody will get wrong later."""
    return str(public_key).replace("-", "")


print("")
print("=== configure these ===")
print("")
print("# Beyou-dev-env/.env — the backend runs inside the compose network, so it")
print("# addresses the collector by service name, not localhost.")
print(f"SENTRY_DSN=http://{dsn_key(dsns['beyou-backend'][0])}@glitchtip:8000/{dsns['beyou-backend'][1]}")
print(
    f"SNAPSHOT_HEARTBEAT_URL=http://glitchtip:8000/api/0/organizations/{org.slug}"
    f"/heartbeat_check/{heartbeat.endpoint_id}/"
)
print("")
print("# Beyou-Frontend/apps/web/.env — inlined into the bundle at BUILD time.")
print("# Changing it needs a rebuild, not a restart.")
print(f"VITE_SENTRY_DSN=http://{dsn_key(dsns['beyou-web'][0])}@localhost:8000/{dsns['beyou-web'][1]}")
print("")
print("# Beyou-Frontend/apps/mobile/.env — also build-time. The device is not on")
print("# localhost, so this needs the host's address on your network.")
print(f"EXPO_PUBLIC_SENTRY_DSN=http://{dsn_key(dsns['beyou-mobile'][0])}@<HOST-LAN-IP>:8000/{dsns['beyou-mobile'][1]}")
