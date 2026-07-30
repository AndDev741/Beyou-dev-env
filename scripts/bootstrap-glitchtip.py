# Idempotent GlitchTip bootstrap. Piped into `manage.py shell` by
# scripts/bootstrap-glitchtip.sh — see that script for why, and run it rather
# than this file directly.
#
# Creates, only when missing: the organization, its team, one project per
# reporting surface, the three monitors, and one alert rule per project with an
# e-mail recipient wired to it. Then prints the DSNs and the heartbeat check-in
# URL, which are the values a deployment has to configure.
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

# The management port is bound to 127.0.0.1, so only a monitor sharing the
# compose network can reach it. That is why GlitchTip lives in the monitoring
# overlay rather than on its own host.
UPTIME_URL = "http://backend:9091/actuator/health"

# The snapshot job runs hourly on the hour. 90 minutes leaves room for one slow
# cycle or a single failed check-in without paging anyone.
HEARTBEAT_PERIOD_SECONDS = 5400

# GlitchTip probes from inside beyou_net, so this must be the CONTAINER port, not
# the published one. Dev runs Vite directly (3000); prod serves the built app
# through nginx (80). Getting this wrong leaves the monitor permanently DOWN in
# whichever environment was not the default, which is worse than no monitor —
# a red light nobody believes.
FRONTEND_TARGET = os.environ.get("GLITCHTIP_FRONTEND_TARGET", "frontend:80")

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
reconcile(uptime, project=backend_project, monitor_type="GET", url=UPTIME_URL,
          expected_status=200, interval=60, timeout=10, confirmation_threshold=2)
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
reconcile(heartbeat, project=backend_project, monitor_type="Heartbeat",
          interval=HEARTBEAT_PERIOD_SECONDS, confirmation_threshold=1)
print(f"monitor 'Snapshot scheduler heartbeat': {'created' if created else 'already present'}")

# TCP Port monitors carry the port in the URL ("frontend:3000"), not in
    # expected_status.  GlitchTip's uptime runner calls url.split(":") and
    # feeds the two parts to asyncio.open_connection — expected_status is
    # only read by the HTTP monitor path (GET / POST / PING).
frontend_project = Project.objects.get(slug="beyou-web", organization=org)
web, created = Monitor.objects.get_or_create(
    name="Beyou web frontend",
    organization=org,
    defaults={
        "project": frontend_project,
        "monitor_type": "TCP Port",
        "url": FRONTEND_TARGET,
        "interval": 60,
        "timeout": 10,
        "confirmation_threshold": 2,
    },
)
reconcile(web, project=frontend_project, monitor_type="TCP Port", url=FRONTEND_TARGET,
          interval=60, timeout=10, confirmation_threshold=2)
print(f"monitor 'Beyou web frontend': {'created' if created else 'already present'}")

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
# monitor event twice.
for slug, _name, _platform in SURFACES:
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
