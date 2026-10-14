"""Queues the CRM timeline mirror again for messages that never reached their record.

Board T57 and the REST throttle of 2026-10-14. From 07:46 UTC that day the Bitrix
nginx refused a few hundred of our calls an hour (429), and the mirror did not try
again, so those messages are in the panel and missing from the timeline, some of
them from one of their records only (a 429 on the lead search, and the Owner Data
card got the line). And Lead AI chats were mirrored to whichever lead the phone
search returned first, rather than to the lead the campaign was sent from, which
is missing them.

This picks the messages and queues ``mirror_message`` for each, spaced out. The
task decides whether the number has a CRM record at all, posts only on the
records that do not hold the message yet (Mirror), and looks on the record's
timeline before it posts (an earlier post may have landed without its answer),
so a second run posts nothing twice.

Picked:

- ``--since`` (UTC): every message created from then on, whatever it reached:
  the task posts only what is missing;
- ``--leadai``: every message of every Lead AI chat, of any date, that is not on
  the chat's own record yet (the lead or deal of the Lead AI campaign that had
  reached the chat by then, else the record the chat came with: tasks.
  _own_record; for a chat without one, no Mirror row at all).

Given both, a message either one picks.

Never picked: panel-only copies (the original is mirrored), the templates our
campaigns sent (a campaign posts its own copy of each: campaigns.services,
renewals.post_deal_timeline; tasks.campaign_sends; the Lead AI's own reminders and
Template B are not among them), reactions, system notes, kinds we cannot read,
sends that failed (the customer never got them), and anything from the last five
minutes (the live mirror and its retries own those).

Oldest first, so each timeline reads in the order the conversation happened. The
i-th task waits i * ``--every`` seconds (8 by default: an unanswered lookup costs
six to eight REST calls, and the background budget is what campaigns, Lead AI and
the panel leave), and tasks are queued only as far as 45 minutes ahead: Redis
hands a task that has waited past the broker's one-hour visibility timeout to a
worker a second time. Whatever is left goes in a later run, which the last line
spells out: from where this run stopped (``--since``), because a message whose
records all hold it, or whose number has none, keeps matching ``--since``, and a
run that started from the beginning again would pick those same messages for ever.

Refused while a campaign is sending: the back-fill would take the REST budget of
its lookups and comments. A dry run says so and counts anyway.

Prints counts only, never a message, a phone or a name.
"""

import operator
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from functools import reduce

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from apps.crmlink import tasks
from apps.crmlink.models import Mirror
from apps.inbox.models import Message

FRESH = timedelta(minutes=5)
HORIZON_SECONDS = 45 * 60
LIMIT_MAX = 20000
EVERY_MIN, EVERY_MAX = 1, 60
EVERY_DEFAULT = 8
SKIP_KINDS = (Message.Kind.REACTION, Message.Kind.SYSTEM, Message.Kind.UNKNOWN)
# A campaign counts as sending while it is RUNNING or RETRYING and has a recipient waiting, or
# one tried this recently. One stuck in RUNNING for longer, with nobody waiting, is not sending.
CAMPAIGN_ACTIVE = timedelta(minutes=30)


def parse_since(text):
    """An ISO-8601 time such as 2026-10-14T07:40:00Z; one without a zone is read as UTC."""
    try:
        moment = datetime.fromisoformat(str(text).strip())
    except ValueError:
        raise CommandError("--since takes an ISO-8601 time in UTC, such as 2026-10-14T07:40:00Z") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt_timezone.utc)
    return moment


def candidates(*, since=None, leadai=False, now=None):
    """The messages to mirror again, as a queryset (not ordered, not limited)."""
    now = now or timezone.now()
    any_mirror = Mirror.objects.filter(message_id=OuterRef("pk"))
    query = Message.objects.all()
    picked = []
    if since is not None:
        picked.append(Q(created_at__gte=since))
    if leadai:
        first, second = tasks.own_record_annotations()
        query = query.annotate(**first).annotate(**second)
        own_mirror = Mirror.objects.filter(
            message_id=OuterRef("pk"),
            entity_type=OuterRef("own_type"),
            entity_id=OuterRef("own_id"),
        )
        in_chat = Q(conversation__lead_ai_chat__isnull=False)
        picked.append(in_chat & Q(own_type__isnull=False) & ~Exists(own_mirror))
        picked.append(in_chat & Q(own_type__isnull=True) & ~Exists(any_mirror))
    if not picked:
        return Message.objects.none()
    return (
        query.filter(reduce(operator.or_, picked))
        .filter(
            direction__in=(Message.Direction.INBOUND, Message.Direction.OUTBOUND),
            mirrored_from__isnull=True,
            created_at__lte=now - FRESH,
        )
        .exclude(kind__in=SKIP_KINDS)
        .exclude(tasks.campaign_sends())
        .exclude(direction=Message.Direction.OUTBOUND, status=Message.Status.FAILED)
    )


def sending_campaigns(now=None):
    """Ids of the campaigns sending now (CAMPAIGN_ACTIVE)."""
    from apps.campaigns.models import Campaign, CampaignRecipient

    now = now or timezone.now()
    busy = CampaignRecipient.objects.filter(campaign_id=OuterRef("pk")).filter(
        Q(status=CampaignRecipient.Status.PENDING) | Q(last_attempt_at__gte=now - CAMPAIGN_ACTIVE)
    )
    return list(
        Campaign.objects.filter(status__in=(Campaign.Status.RUNNING, Campaign.Status.RETRYING))
        .filter(Exists(busy))
        .order_by("pk")
        .values_list("pk", flat=True)
    )


def _utc(moment):
    return moment.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tally(values):
    counts = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return ", ".join(f"{key} {count}" for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])))


class Command(BaseCommand):
    help = (
        "Queues the CRM timeline mirror again for messages since a time (--since) and for Lead AI chat "
        "messages missing from their own lead (--leadai). Prints counts only."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--since", help="UTC time, e.g. 2026-10-14T07:40:00Z: every message from then on (only what is missing is posted)."
        )
        parser.add_argument(
            "--leadai",
            action="store_true",
            help="Every message of every Lead AI chat, any date, not on the chat's own record yet.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Count and report; queue nothing.")
        parser.add_argument("--limit", type=int, default=2000, help=f"At most this many messages (1-{LIMIT_MAX}).")
        parser.add_argument(
            "--every",
            type=int,
            default=EVERY_DEFAULT,
            help=f"Seconds between two queued tasks ({EVERY_MIN}-{EVERY_MAX}, default {EVERY_DEFAULT}).",
        )

    def handle(self, *args, **options):
        since = parse_since(options["since"]) if options.get("since") else None
        leadai = bool(options.get("leadai"))
        limit, every = options["limit"], options["every"]
        if since is None and not leadai:
            raise CommandError("Say what to back-fill: --since TIME, --leadai, or both.")
        if not 1 <= limit <= LIMIT_MAX:
            raise CommandError(f"--limit takes 1 to {LIMIT_MAX}.")
        if not EVERY_MIN <= every <= EVERY_MAX:
            raise CommandError(f"--every takes {EVERY_MIN} to {EVERY_MAX} seconds.")

        sending = sending_campaigns()
        if sending and not options.get("dry_run"):
            raise CommandError(
                f"Campaign {', '.join(str(pk) for pk in sending)} is sending now; the back-fill would take its "
                "Bitrix budget. Run this again once it is done."
            )

        query = candidates(since=since, leadai=leadai)
        matching = query.count()
        selected = list(query.order_by("created_at", "id").values_list("pk", "direction", "kind", "created_at")[:limit])
        # Countdowns 0, every, 2 * every, ... no further than the horizon.
        fits = HORIZON_SECONDS // every + 1
        batch = selected[:fits]

        picked = []
        if since is not None:
            picked.append(f"every message since {_utc(since)} (only what is missing is posted)")
        if leadai:
            picked.append("Lead AI chat messages not on their own record")
        self.stdout.write(f"Picked: {'; '.join(picked)}.")
        self.stdout.write(
            "Left out: panel copies, campaign templates, reactions, system notes, unknown kinds, "
            f"failed sends, and the last {int(FRESH.total_seconds() // 60)} minutes."
        )
        self.stdout.write(f"Matching messages: {matching}. This run: {len(batch)} (limit {limit}, one every {every} s).")
        if batch:
            self.stdout.write(f"  direction: {_tally(direction for _, direction, _, _ in batch)}")
            self.stdout.write(f"  kind: {_tally(kind for _, _, kind, _ in batch)}")
            first = min(created for _, _, _, created in batch)
            last = max(created for _, _, _, created in batch)
            self.stdout.write(f"  created_at: first {_utc(first)}, last {_utc(last)}")

        if options.get("dry_run"):
            self.stdout.write("Dry run: nothing was queued.")
            if sending:
                self.stdout.write(
                    f"Campaign {', '.join(str(pk) for pk in sending)} is sending now: a real run would be refused until it is done."
                )
            if matching > len(batch):
                self.stdout.write(f"{matching - len(batch)} more match beyond this run.")
            return

        queued = 0
        for index, (pk, _, _, _) in enumerate(batch):
            try:
                # No summary from a back-fill: the conversation's message count says nothing
                # about an old message, and every one of them would ask for one. And a look at
                # the timeline before each post: an earlier post may have landed unrecorded.
                tasks.mirror_message.apply_async(
                    args=[pk], kwargs={"summary_check": False, "look_first": True}, countdown=index * every
                )
            except Exception as exc:  # noqa: BLE001 - say how far it got; a second run picks up the rest
                self.stderr.write(f"The broker refused a task ({type(exc).__name__}); {queued} were queued.")
                break
            queued += 1

        if queued:
            span = (queued - 1) * every
            when = f"in about {(span + 59) // 60} minutes" if span >= 60 else f"in {span} s"
            self.stdout.write(f"Queued {queued} mirror tasks; the last runs {when}.")
        else:
            self.stdout.write("Nothing was queued.")
        self._next_run(matching - queued, batch[:queued], since, leadai)

    def _next_run(self, left, done, since, leadai):
        """What to run next, when more match than this run took."""
        if left <= 0:
            return
        if since is None or not done:
            # Lead AI messages land on their own lead and so stop matching; the same run again
            # goes on with the rest.
            self.stdout.write(f"{left} more match: run this again once these have run.")
            return
        # Every message since then keeps matching --since; start after this run.
        resume = max(since, max(created for _, _, _, created in done))
        flags = f"--since {_utc(resume)}" + (" --leadai" if leadai else "")
        self.stdout.write(f"{left} more match. Once these have run, go on from where this run stopped: {flags}")
