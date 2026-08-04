# Idempotent GlitchTip bootstrap. Piped into `manage.py shell` by
# scripts/bootstrap-glitchtip.sh — see that script for why, and run it rather
# than this file directly.
#
# Creates, only when missing: the organization, its team, one project per
# reporting surface (backend/web/mobile) plus an infrastructure project, one
# uptime monitor per Beyou container, the snapshot-scheduler heartbeat, and
# one alert rule per project with an e-mail recipient wired to it. Then prints
# the DSNs and the heartbeat check-in URL, which are the values a deployment
# has to configure.
#
# Creation is get_or_create, but the run does NOT stop there: reconcile() writes
# this file's values back over whatever is in the database, so a second run
# repairs drift rather than reporting "already present" and leaving a wrong
# probe target or a de-wired recipient in place. That overwrite is the point —
# this file, not the UI, is the source of truth for everything it manages.
#
# It never sets a password. The first account is registered in the UI; an alert
# recipient that is not that account is created with an unusable password (see
# resolve_recipient below).

import os

from django.apps import apps
from django.conf import settings

Organization = apps.get_model("organizations_ext", "Organization")
OrganizationUser = apps.get_model("organizations_ext", "OrganizationUser")
Team = apps.get_model("teams", "Team")
Project = apps.get_model("projects", "Project")
ProjectKey = apps.get_model("projects", "ProjectKey")
UserProjectAlert = apps.get_model("projects", "UserProjectAlert")
Monitor = apps.get_model("uptime", "Monitor")
ProjectAlert = apps.get_model("alerts", "ProjectAlert")
AlertRecipient = apps.get_model("alerts", "AlertRecipient")
User = apps.get_model("users", "User")

ORG_SLUG = "beyou"
TEAM_SLUG = "beyou-dev"

# Org role for a recipient this script creates. MEMBER (0) is the least it can
# be and still receive alerts — recipient resolution walks
# OrganizationUser -> teams -> projects, so an address with no org membership is
# simply never mailed. Nothing here needs write access.
ORG_ROLE_MEMBER = 0

# One alert rule per project, keyed on this name. "Every new issue, immediately":
# quantity=1 over a 1-minute window. GlitchTip's evaluator
# (apps.alerts.tasks.process_event_alerts, every ALERT_NOTIFICATION_INTERVAL=60s)
# skips any rule where quantity OR timespan_minutes is null, which is why both
# are set even though "1 event" needs no real window. It excludes issues already
# notified for this rule, so a noisy issue mails once, not once per minute.
ALERT_NAME = "New issue"
ALERT_QUANTITY = 1
ALERT_TIMESPAN_MINUTES = 1

# One project per surface. Errors from three different runtimes group, alert and
# resolve independently, and source maps upload per project — a single shared
# project makes all three worse.
SURFACES = [
    ("beyou-backend", "Beyou Backend", "java-spring-boot"),
    ("beyou-web", "Beyou Web", "javascript-react"),
    ("beyou-mobile", "Beyou Mobile", "react-native"),
]

# --- uptime monitor targets --------------------------------------------------
# GlitchTip probes from inside beyou_net, so every target is a CONTAINER
# address: the container port, never the published host one (most of these are
# not even published). Defaults match the compose stack; override any of them
# in .env when a deployment names or ports things differently. A wrong target
# here leaves the monitor permanently DOWN, which is worse than no monitor —
# a red light nobody believes.
def _target(name, default):
    return os.environ.get(name, "").strip() or default

# The management server answers on 0.0.0.0:9091 INSIDE the container
# (MANAGEMENT_ADDRESS=0.0.0.0 in .env); 127.0.0.1 is only the host-side binding
# of the published port. That is why only a monitor sharing the compose network
# can reach it, and why GlitchTip lives in the monitoring overlay.
BACKEND_TARGET = _target("GLITCHTIP_BACKEND_TARGET", "http://backend:9091/actuator/health")

# Dev runs Vite directly (3000); prod serves the built app through nginx (80).
FRONTEND_TARGET = _target("GLITCHTIP_FRONTEND_TARGET", "frontend:80")

DB_TARGET = _target("GLITCHTIP_DB_TARGET", "db:5432")
# The collector's datastores live on glitchtip_net, and GlitchTip is
# dual-homed, so it resolves these names even though the app network cannot.
GLITCHTIP_DB_TARGET = _target("GLITCHTIP_GLITCHTIP_DB_TARGET", "glitchtip-db:5432")
VALKEY_TARGET = _target("GLITCHTIP_VALKEY_TARGET", "glitchtip-valkey:6379")

LOKI_TARGET = _target("GLITCHTIP_LOKI_TARGET", "http://loki:3100/ready")
# /-/healthy is stronger than liveness: 500 when ANY component of Alloy's
# pipeline is unhealthy, which is exactly the signal a log pipeline needs.
ALLOY_TARGET = _target("GLITCHTIP_ALLOY_TARGET", "http://alloy:12345/-/healthy")
PROMETHEUS_TARGET = _target("GLITCHTIP_PROMETHEUS_TARGET", "http://prometheus:9090/-/healthy")
GRAFANA_TARGET = _target("GLITCHTIP_GRAFANA_TARGET", "http://grafana:3000/api/health")
# Same path the container's own healthcheck.py probes; the collector watching
# itself is for the Uptime page, NOT for alerting — a wedged GlitchTip cannot
# send its own alerts, which is what Prometheus' up{job="glitchtip"} is for.
GLITCHTIP_TARGET = _target("GLITCHTIP_GLITCHTIP_TARGET", "http://glitchtip:8000/_health/")

# watchtower only exists in the prod overlay. Empty (the default) skips the
# monitor entirely — dev has no watchtower, and a permanently red monitor
# nobody believes is worse than none. Set GLITCHTIP_WATCHTOWER_TARGET=watchtower:8080
# where watchtower runs (its HTTP API must be enabled; see docker-compose.prod.yml).
WATCHTOWER_TARGET = os.environ.get("GLITCHTIP_WATCHTOWER_TARGET", "").strip()

# The snapshot job runs hourly on the hour. 90 minutes leaves room for one slow
# cycle or a single failed check-in without paging anyone.
HEARTBEAT_PERIOD_SECONDS = 5400

# Where alerts go. Empty means "the first registered account", which is already
# a team member and therefore already a valid recipient — so the default stack
# alerts somebody rather than nobody. Set it to a shared ops mailbox for a
# deployed stack.
ALERT_EMAIL = (os.environ.get("GLITCHTIP_ALERT_EMAIL") or "").strip()

def reconcile(obj, **fields):
    """Django applies `defaults` only on creation, so a re-run of get_or_create
    reports "already present" and silently keeps whatever drifted — including a
    wrong probe target. Writing the script's own values back is what makes the
    idempotence claim true rather than "creates once, then lies"."""
    label = getattr(obj, "name", None) or f"{type(obj).__name__} {obj.pk}"
    changed = [k for k, v in fields.items() if getattr(obj, k) != v]
    if not changed:
        return
    for k, v in fields.items():
        setattr(obj, k, v)
    obj.save(update_fields=list(fields))
    print(f"  reconciled {label}: {', '.join(changed)}")


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

def resolve_recipient():
    """Return the User that alert e-mail will actually reach.

    GlitchTip does NOT mail the address on AlertRecipient — that field is only
    read by the webhook types. For recipient_type="email" it discards it and
    resolves live Users instead
    (users.UserManager.alert_notification_recipients / uptime_monitor_recipients),
    following OrganizationUser -> teams -> projects. So an address only receives
    anything if it is a User, in this organization, on the team that holds the
    project. Creating the AlertRecipient row without that chain produces a rule
    that fires, finds nobody, and returns silently — the exact failure this
    script exists to prevent.

    A recipient that is not the first account is created here with an unusable
    password: it is a mailbox, not a login. Whoever needs the UI uses the
    password-reset flow, which sets a password this script never sees.
    """
    if not ALERT_EMAIL or ALERT_EMAIL.lower() == owner.email.lower():
        # Same outcome either way, but say which — reporting "unset" when the
        # variable is set and merely matches sends the next person debugging
        # this to look in the wrong place.
        why = "GLITCHTIP_ALERT_EMAIL matches it" if ALERT_EMAIL else "GLITCHTIP_ALERT_EMAIL unset"
        print(f"alert recipient {owner.email}: first registered account ({why})")
        user = owner
    else:
        # The email column carries a case-insensitive collation, so this match
        # is already case-folded by Postgres.
        user = User.objects.filter(email=ALERT_EMAIL).first()
        if user is None:
            user = User.objects.create(email=ALERT_EMAIL, subscribe_by_default=True)
            user.set_unusable_password()
            user.save(update_fields=["password"])
            print(f"alert recipient {user.email}: created (notification-only, no password)")
        else:
            print(f"alert recipient {user.email}: already present")

    # _exclude_recipients() drops any user who has neither subscribe_by_default
    # nor an explicit per-project ON. Left False, the rule mails nobody.
    reconcile(user, subscribe_by_default=True)

    org_user, created = OrganizationUser.objects.get_or_create(
        organization=org, user=user, defaults={"role": ORG_ROLE_MEMBER}
    )
    print(f"  org membership: {'created' if created else 'already present'}")
    if not team.members.filter(pk=org_user.pk).exists():
        team.members.add(org_user)
        print(f"  added to team {team.slug}")

    # A per-project OFF beats everything above, and it is set from the UI, so the
    # script must not silently overwrite a human's opt-out — but it must say so,
    # or the rule looks wired and mails nobody.
    muted = list(
        UserProjectAlert.objects.filter(user=user, project__organization=org, status=0)
        .values_list("project__slug", flat=True)
    )
    if muted:
        print(f"  WARNING: {user.email} has alerts OFF for: {', '.join(muted)}")
        print("  Turn them back on in Settings -> Projects -> <project> -> Alerts.")
    return user


recipient = resolve_recipient()

def reconcile_monitor(name, project, monitor_type, url=None, expected_status=None,
                      interval=60, timeout=10, confirmation_threshold=2):
    """get_or_create + reconcile for one uptime monitor. TCP Port monitors
    carry the port in the URL ("frontend:3000") and expected_status stays
    unset — GlitchTip's runner calls url.split(":") and feeds the parts to
    asyncio.open_connection; expected_status is only read on the HTTP paths
    (GET / POST / PING)."""
    defaults = {
        "project": project,
        "monitor_type": monitor_type,
        "interval": interval,
        "timeout": timeout,
        # Two consecutive failures before alerting: one dropped poll during a
        # restart is not an outage.
        "confirmation_threshold": confirmation_threshold,
    }
    if url is not None:
        defaults["url"] = url
    if expected_status is not None:
        defaults["expected_status"] = expected_status
    monitor, created = Monitor.objects.get_or_create(
        name=name, organization=org, defaults=defaults
    )
    reconcile(monitor, **defaults)
    print(f"monitor '{name}': {'created' if created else 'already present'}")
    return monitor

backend_project = Project.objects.get(slug="beyou-backend", organization=org)
reconcile_monitor("Beyou backend health", backend_project, "GET", BACKEND_TARGET, 200)
heartbeat = reconcile_monitor(
    "Snapshot scheduler heartbeat", backend_project, "Heartbeat",
    interval=HEARTBEAT_PERIOD_SECONDS, confirmation_threshold=1,
)

frontend_project = Project.objects.get(slug="beyou-web", organization=org)
reconcile_monitor("Beyou web frontend", frontend_project, "TCP Port", FRONTEND_TARGET)

# --- infrastructure monitors -------------------------------------------------
# One project per surface, same rule as the app projects: alerts join through
# the project, so infra monitors get their own project and their own alert
# rule, and a glitchtip-db outage is not mailed from the "Beyou Backend"
# project. No DSN: nothing reports errors to it, it only hosts monitors.
infra_project, created = Project.objects.get_or_create(
    slug="beyou-infra",
    organization=org,
    defaults={"name": "Beyou Infra", "platform": "other"},
)
infra_project.teams.add(team)
print(f"project beyou-infra: {'created' if created else 'already present'}")

INFRA_MONITORS = [
    ("Beyou postgres (app DB)", "TCP Port", DB_TARGET, None),
    ("Beyou glitchtip postgres", "TCP Port", GLITCHTIP_DB_TARGET, None),
    ("Beyou glitchtip valkey", "TCP Port", VALKEY_TARGET, None),
    ("Beyou loki", "GET", LOKI_TARGET, 200),
    ("Beyou alloy", "GET", ALLOY_TARGET, 200),
    ("Beyou prometheus", "GET", PROMETHEUS_TARGET, 200),
    ("Beyou grafana", "GET", GRAFANA_TARGET, 200),
    ("Beyou glitchtip (self)", "GET", GLITCHTIP_TARGET, 200),
]
if WATCHTOWER_TARGET:
    INFRA_MONITORS.append(("Beyou watchtower", "TCP Port", WATCHTOWER_TARGET, None))

for monitor_name, monitor_type, url, expected_status in INFRA_MONITORS:
    reconcile_monitor(monitor_name, infra_project, monitor_type, url, expected_status)

# --- alert rules -------------------------------------------------------------
# Without these, everything above is decorative: events are stored, monitors go
# red, and nothing is sent. Two separate code paths both terminate here, and both
# need an AlertRecipient to exist or they no-op:
#
#   errors  -> alerts.tasks.process_event_alerts picks rules with quantity and
#              timespan_minutes set, then Notification.send_notifications().
#   uptime  -> uptime.tasks.send_monitor_notification filters
#              AlertRecipient(alert__project__monitor=<monitor>, alert__uptime=True).
#              Heartbeat misses travel this same path, so uptime=True is what
#              makes the snapshot-scheduler monitor able to tell anyone.
#
# Exactly ONE rule per project, deliberately: that uptime filter joins through
# the project, so a second uptime=True rule on beyou-backend would mail every
# monitor event twice. The infra project joins the loop for the same reason —
# its monitors alert through its own single rule.
for slug in [s[0] for s in SURFACES] + ["beyou-infra"]:
    project = Project.objects.get(slug=slug, organization=org)
    alert, created = ProjectAlert.objects.get_or_create(
        project=project,
        name=ALERT_NAME,
        defaults={
            "quantity": ALERT_QUANTITY,
            "timespan_minutes": ALERT_TIMESPAN_MINUTES,
            "uptime": True,
        },
    )
    reconcile(alert, quantity=ALERT_QUANTITY,
              timespan_minutes=ALERT_TIMESPAN_MINUTES, uptime=True)

    # unique_together is (alert, recipient_type, url), and url stays empty for
    # e-mail — so this is one row per rule and re-running cannot duplicate it.
    _recipient_row, recipient_created = AlertRecipient.objects.get_or_create(
        alert=alert, recipient_type="email", url=""
    )
    print(
        f"alert '{ALERT_NAME}' on {slug}: {'created' if created else 'already present'}"
        f", email recipient {'created' if recipient_created else 'already present'}"
    )


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
print("=== mail transport ===")
print("")
# Read from inside the collector, so this reports what the container actually
# resolved rather than what .env was believed to say. A stack where every rule is
# wired but EMAIL_URL is still consolemail:// is quiet in exactly the way that
# looks healthy, so say it out loud on every run.
print(f"alerts will be addressed to: {recipient.email}")
if not getattr(settings, "EMAIL_ENABLED", True):
    print("EMAIL IS DISABLED in this container — no alert can leave. Set GLITCHTIP_EMAIL_URL.")
elif "console" in settings.EMAIL_BACKEND:
    print("EMAIL_URL=consolemail:// — mail is PRINTED TO THE CONTAINER LOG, not sent.")
    print("  Watch it with:  docker logs -f <glitchtip-container>")
    print("  For a real send, set GLITCHTIP_EMAIL_URL in .env (see .env.example).")
else:
    print(f"backend: {settings.EMAIL_BACKEND}")
    print(f"host:    {getattr(settings, 'EMAIL_HOST', '?')}:{getattr(settings, 'EMAIL_PORT', '?')}"
          f"  tls={getattr(settings, 'EMAIL_USE_TLS', False)} ssl={getattr(settings, 'EMAIL_USE_SSL', False)}")
    print(f"from:    {settings.DEFAULT_FROM_EMAIL}")
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
