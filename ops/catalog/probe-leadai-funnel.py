# Read-only, run through `ops/wa.sh probe-leadai-funnel [--weeks N]` (board T73, Claude's half of the
# weekly funnel; Cursor's Bitrix half is ops/bitrix-aws/a7_c30_funnel.php, its definitions under "C30" on
# SHOPS-BOT-BOARD.md).
#
# The WhatsApp side of the Lead AI funnel per ISO week (Asia/Dubai), per playbook (ic_shops, general) and in
# total. A row's week is the week its campaign messages went out. What a chat did after a campaign message,
# until the next Lead AI campaign message that reached the same chat (the message's stretch), is counted on
# that message's row, so the later columns of a recent week still grow as its chats answer. A campaign message
# that never reached the customer (`failed` below) ends no stretch and has an empty one: nothing counts on it.
#
#   sent        campaign messages the gateway accepted (one per campaign and phone; a retry is the same one)
#   delivered   of those, Meta said delivered or read
#   read        of those, Meta said read (a customer with read receipts off never shows as read)
#   failed      campaign messages that did not reach the customer: refused by the gateway (never sent), or
#               reported failed by Meta after it was sent. One the campaign may still retry counts here too.
#   replied     chats with any message from the customer after the campaign message
#   booked      chats with a confirmed visit (the assistant confirmed a time; later cancelled or past still counts)
#   handovers   chats handed to a person: by the assistant (it asked for a person, a call, a broker, ...), or by
#               a person setting Bot Status Handed or Broker in Bitrix (seen while the chat still holds it)
#   opt_outs    chats that asked us to stop: a STOP or a wrong number the assistant read, an Unsubscribe or Stop
#               tap, or Opted out set in Bitrix. Spam and automatic replies are not opt-outs.
#   median_answer_min  median minutes from the customer's first message after the campaign message to our
#               first message after it (the assistant's or a person's, accepted by the gateway; a template is
#               no answer), over the chats that got one within the message's stretch: `answered` chats
#
# A chat reached by both playbooks in one week counts once in its total row. Recipients whose phone is on the
# Lead AI settings' test-number list ("Test numbers" on the Lead AI screen: staff phones) are left out of every
# count, and CHECKS says how many. Counts only: no phone number, name or message text is printed. One
# transaction, which PostgreSQL is told is READ ONLY and which is always rolled back. LEADAI_FUNNEL_WEEKS
# (ops/wa.sh passes --weeks N, 1-26; default 8) sets how many weeks.
import datetime as dt
import os
import statistics
from collections import Counter, defaultdict
from zoneinfo import ZoneInfo

from django.db import connection, transaction
from django.utils import timezone

from apps.campaigns.models import CampaignRecipient
from apps.inbox.models import Message
from apps.leadai.models import (
    LeadAiAlert, LeadAiAppointment, LeadAiCampaign, LeadAiChatState, LeadAiOptOut, LeadAiSettings, LeadAiTurn,
)

DUBAI = ZoneInfo("Asia/Dubai")
PLAYBOOKS = ("ic_shops", "general")
TOTAL = "total"
ALL = "all"
# A campaign message is the template message stored with the send: same chat, same template, made just
# before the gateway accepted it (process_recipient stamps sent_at right after the call; 1-2 s on live data).
MATCH_BEFORE = dt.timedelta(minutes=10)
MATCH_AFTER = dt.timedelta(minutes=1)
NOT_A_REPLY = {"system", "reaction"}
NOT_AN_ANSWER = {"template", "system", "reaction", "pinned_message"}
ACCEPTED = {"sent", "delivered", "read"}
FAILED = {"failed", "exhausted"}
STOPS = {"stop_all", "wrong_number"}
# "import" rows carry the time of the back-fill, not of the customer's words; leadai_spam is our own reading.
OPT_OUT_SOURCES = {"leadai_stop", "wrong_number", "inbox_tap", "bitrix"}
# A Broker set in Bitrix (bitrix_status.py) stamps handed_over_at with the assistant's own broker reason
# (engine.BROKER), then raises a "bitrix_status" alert for the chat whose key's third part is the Bot Status
# (bitrix_status.BROKER): that alert, raised right after the stamp, is what marks the handover as Bitrix's.
BROKER_REASON = "broker_or_for_client"
BITRIX_BROKER = "2479"
BITRIX_ALERT_WITHIN = dt.timedelta(minutes=5)
CHUNK = 500
COLUMNS = (
    "sent", "delivered", "read", "failed", "replied", "booked", "handovers", "opt_outs", "median_answer_min", "answered",
)


class Rollback(Exception):
    pass


def weeks_wanted():
    try:
        weeks = int(os.environ.get("LEADAI_FUNNEL_WEEKS") or 8)
    except ValueError:
        weeks = 8
    return min(max(weeks, 1), 26)


def week_of(moment):
    year, week, _ = moment.astimezone(DUBAI).isocalendar()
    return f"{year}-W{week:02d}"


def chunks(values):
    values = sorted(values)
    for start in range(0, len(values), CHUNK):
        yield values[start : start + CHUNK]


def digits(text):
    """The digits of a phone, as LeadAiSettings.answers() compares the test numbers."""
    return "".join(ch for ch in str(text or "") if ch.isdigit())


def parse_moment(text):
    try:
        moment = dt.datetime.fromisoformat(str(text or ""))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.timezone.utc)


def first_after(times, start, end):
    """The first moment of the sorted ``times`` after ``start`` and before ``end`` (None: no end)."""
    for moment in times:
        if moment <= start:
            continue
        return moment if end is None or moment < end else None
    return None


def sources_within(events, start, end):
    """The sources of the (moment, source) events from ``start`` up to ``end``."""
    return {source for moment, source in events if moment >= start and (end is None or moment < end)}


def empty_row():
    return {
        "sent": 0, "delivered": 0, "read": 0, "failed": 0,
        "replied": set(), "booked": set(), "handovers": set(), "opt_outs": set(),
        "first_reply": {},  # chat -> (its first reply in this row, minutes to our answer or None)
    }


def cells(row):
    minutes = [value for _, value in row["first_reply"].values() if value is not None]
    median = f"{statistics.median(minutes):.1f}" if minutes else "-"
    return [
        row["sent"], row["delivered"], row["read"], row["failed"], len(row["replied"]), len(row["booked"]),
        len(row["handovers"]), len(row["opt_outs"]), median, len(minutes),
    ]


def probe():
    weeks = weeks_wanted()
    now = timezone.now()
    local_now = now.astimezone(DUBAI)
    this_monday = (local_now - dt.timedelta(days=local_now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    first_monday = this_monday - dt.timedelta(weeks=weeks - 1)
    labels = [week_of(first_monday + dt.timedelta(weeks=i)) for i in range(weeks)]

    # The Lead AI campaigns and their recipients, but those on the test-number list (a phone is read only to
    # leave those out, and never printed).
    campaigns = {}
    for campaign_id, playbook, template_id, created_at in LeadAiCampaign.objects.values_list(
        "campaign_id", "playbook", "campaign__template_id", "campaign__created_at"
    ):
        campaigns[campaign_id] = (playbook if playbook in PLAYBOOKS else "general", template_id, created_at)
    test_numbers = LeadAiSettings.objects.filter(pk=1).values_list("test_numbers", flat=True).first()
    tests = {digits(number) for number in (test_numbers if isinstance(test_numbers, list) else [])} - {""}
    recipients, testers = [], 0
    for ids in chunks(campaigns):
        for row in CampaignRecipient.objects.filter(campaign_id__in=ids).values_list(
            "id", "campaign_id", "status", "sent_at", "last_attempt_at", "created_at", "conversation_id", "phone"
        ):
            if digits(row[7]) in tests:
                testers += 1
            else:
                recipients.append(row[:7])
    chats = {row[6] for row in recipients if row[6]}

    # The chats' messages, oldest first: kinds, statuses and times only, never a body or a payload.
    inbound, answers, templates = defaultdict(list), defaultdict(list), defaultdict(list)
    for ids in chunks(chats):
        rows = (
            Message.objects.filter(conversation_id__in=ids, mirrored_from__isnull=True)
            .order_by("created_at", "id")
            .values_list("id", "conversation_id", "direction", "kind", "status", "template_id", "created_at", "delivered_at", "read_at")
        )
        for pk, chat, direction, kind, status, template_id, created_at, delivered_at, read_at in rows.iterator(chunk_size=2000):
            if direction == Message.Direction.INBOUND:
                if kind not in NOT_A_REPLY:
                    inbound[chat].append(created_at)
            elif kind == Message.Kind.TEMPLATE:
                templates[chat].append((pk, template_id, created_at, status, delivered_at, read_at))
            elif kind not in NOT_AN_ANSWER and status in ACCEPTED:
                answers[chat].append(created_at)

    # One send per recipient that was accepted, or refused by the gateway.
    sends, used = [], set()
    unmatched = refused = retry_due = in_flight = 0
    for rid, campaign_id, status, sent_at, last_attempt_at, created_at, chat in sorted(
        recipients, key=lambda row: (row[3] or row[4] or row[5], row[0])
    ):
        playbook, template_id, _ = campaigns[campaign_id]
        if sent_at is None:
            if status in FAILED:
                refused += 1
                retry_due += status == CampaignRecipient.Status.FAILED
                sends.append({"playbook": playbook, "moment": last_attempt_at or created_at, "accepted": False,
                              "delivered": False, "read": False, "failed": True, "chat": None})
            continue
        message = None
        for item in templates.get(chat, ()) if chat else ():
            pk, tpl, made = item[0], item[1], item[2]
            if pk in used or tpl != template_id or not sent_at - MATCH_BEFORE <= made <= sent_at + MATCH_AFTER:
                continue
            if message is None or made >= message[2]:
                message = item
        delivered = read = message_failed = False
        if message is None:
            unmatched += 1
        else:
            used.add(message[0])
            _, _, _, message_status, delivered_at, read_at = message
            read = message_status == Message.Status.READ or read_at is not None
            delivered = read or message_status == Message.Status.DELIVERED or delivered_at is not None
            message_failed = message_status == Message.Status.FAILED
        failed = (status in FAILED or message_failed) and not delivered
        retry_due += failed and status in (CampaignRecipient.Status.FAILED, CampaignRecipient.Status.PENDING)
        in_flight += message is not None and not failed and not delivered
        sends.append({"playbook": playbook, "moment": sent_at, "accepted": True, "delivered": delivered, "read": read,
                      "failed": failed, "chat": chat, "start": message[2] if message else sent_at, "end": None, "rid": rid})

    # Each campaign message's stretch of its chat ends where the next Lead AI campaign message that reached it
    # begins. One that never reached the customer (refused by the gateway, or failed by Meta after it was sent)
    # ends no stretch, and its own is empty: the customer never saw it.
    by_chat = defaultdict(list)
    for send in sends:
        if send["chat"]:
            by_chat[send["chat"]].append(send)
    for items in by_chat.values():
        reached = sorted((send for send in items if not send["failed"]), key=lambda send: (send["start"], send["rid"]))
        for this, following in zip(reached, reached[1:] + [None]):
            this["end"] = following["start"] if following else None
        for send in items:
            if send["failed"]:
                send["end"] = send["start"]

    # What the chats did, each with its time: visits, handovers, stops.
    booked, tentative, handovers, opt_outs, auto_replies = (defaultdict(list) for _ in range(5))
    backfilled = 0
    for ids in chunks(by_chat):
        for chat, status, created_at, history in LeadAiAppointment.objects.filter(conversation_id__in=ids).values_list(
            "conversation_id", "status", "created_at", "history"
        ):
            events = [entry for entry in (history or []) if isinstance(entry, dict)]
            at = next(
                (parse_moment(e.get("at")) for e in events if e.get("event") in ("confirmed", "rescheduled") and parse_moment(e.get("at"))),
                None,
            )
            if at is None and (status == LeadAiAppointment.Status.CONFIRMED or any(e.get("event") == "past" for e in events)):
                at = created_at
            (booked if at is not None else tentative)[chat].append((at or created_at, "visit"))
        for chat, created_at, finished_at, actions in LeadAiTurn.objects.filter(conversation_id__in=ids).filter(
            actions__has_key="handover"
        ).values_list("conversation_id", "created_at", "finished_at", "actions"):
            if (actions or {}).get("handover"):
                handovers[chat].append((finished_at or created_at, "assistant"))
        for chat, created_at, finished_at, actions in LeadAiTurn.objects.filter(conversation_id__in=ids).filter(
            actions__has_key="opt_out"
        ).values_list("conversation_id", "created_at", "finished_at", "actions"):
            if (actions or {}).get("opt_out") in STOPS:
                opt_outs[chat].append((finished_at or created_at, "assistant"))
        for chat, created_at in LeadAiAlert.objects.filter(
            conversation_id__in=ids, kind="handover", dedupe_key__startswith="handover:"
        ).values_list("conversation_id", "created_at"):
            handovers[chat].append((created_at, "assistant"))
        broker_set = defaultdict(list)
        for chat, key, created_at in LeadAiAlert.objects.filter(conversation_id__in=ids, kind="bitrix_status").values_list(
            "conversation_id", "dedupe_key", "created_at"
        ):
            if str(key or "").split(":")[2:3] == [BITRIX_BROKER]:
                broker_set[chat].append(created_at)
        for chat, handed_at, reason, stopped_at, stop_reason in LeadAiChatState.objects.filter(conversation_id__in=ids).values_list(
            "conversation_id", "handed_over_at", "handover_reason", "stopped_at", "stop_reason"
        ):
            if handed_at is not None:
                # bitrix_status.py is the only writer of handed_over_at besides the assistant's own turn: Handed to
                # agent with its own reason, Broker with the assistant's, told apart by its alert.
                from_bitrix = str(reason or "").startswith("Bitrix") or (
                    reason == BROKER_REASON
                    and any(handed_at <= at <= handed_at + BITRIX_ALERT_WITHIN for at in broker_set.get(chat, ()))
                )
                handovers[chat].append((handed_at, "bitrix" if from_bitrix else "state"))
            if stopped_at is not None and stop_reason in STOPS:
                opt_outs[chat].append((stopped_at, "state"))
            if stopped_at is not None and stop_reason == LeadAiChatState.StopReason.AUTO_REPLY:
                auto_replies[chat].append((stopped_at, "auto_reply"))
        for chat, created_at, source in LeadAiOptOut.objects.filter(conversation_id__in=ids).values_list(
            "conversation_id", "created_at", "source"
        ):
            if source in OPT_OUT_SOURCES:
                opt_outs[chat].append((created_at, source))
            elif source == LeadAiOptOut.Source.IMPORT:
                backfilled += 1

    # The rows: every send on its week's playbook and total rows, and on the all-time ones.
    rows = defaultdict(empty_row)
    handover_sources, opt_out_sources, tentative_chats, auto_reply_chats = Counter(), Counter(), set(), set()
    first_label = labels[0]
    before = 0
    for send in sends:
        week = week_of(send["moment"])
        if send["moment"] < first_monday:
            before += 1
        facts = {}
        chat = send["chat"]
        if chat:
            start, end = send["start"], send["end"]
            reply = first_after(inbound.get(chat, ()), start, end)
            if reply is not None:
                answer = first_after(answers.get(chat, ()), reply, end)
                facts["reply"] = (reply, (answer - reply).total_seconds() / 60 if answer is not None else None)
                if sources_within(auto_replies.get(chat, ()), start, end):
                    auto_reply_chats.add(chat)
            facts["booked"] = bool(sources_within(booked.get(chat, ()), start, end))
            if sources_within(tentative.get(chat, ()), start, end) and not facts["booked"]:
                tentative_chats.add(chat)
            who = sources_within(handovers.get(chat, ()), start, end)
            facts["handover"] = bool(who)
            if who:
                handover_sources[(chat, "assistant" if "assistant" in who else "bitrix" if "bitrix" in who else "state")] += 1
            stops = sources_within(opt_outs.get(chat, ()), start, end)
            facts["opt_out"] = bool(stops)
            for source in stops:
                opt_out_sources[(chat, source)] += 1
        for key in ((week, send["playbook"]), (week, TOTAL), (ALL, send["playbook"]), (ALL, TOTAL)):
            row = rows[key]
            row["sent"] += send["accepted"]
            row["delivered"] += send["delivered"]
            row["read"] += send["read"]
            row["failed"] += send["failed"]
            if not chat:
                continue
            if "reply" in facts:
                row["replied"].add(chat)
                kept = row["first_reply"].get(chat)
                if kept is None or facts["reply"][0] < kept[0]:
                    row["first_reply"][chat] = facts["reply"]
            if facts["booked"]:
                row["booked"].add(chat)
            if facts["handover"]:
                row["handovers"].add(chat)
            if facts["opt_out"]:
                row["opt_outs"].add(chat)

    print(f"LEADAI_FUNNEL weeks={weeks} {first_label}..{labels[-1]} now={local_now:%Y-%m-%d %H:%M} Asia/Dubai")
    print("== BY_WEEK (the ISO week the campaign message went out; newest first) ==")
    print("iso_week\tplaybook\t" + "\t".join(COLUMNS))
    for label in reversed(labels):
        for playbook in (*PLAYBOOKS, TOTAL):
            print("\t".join(str(value) for value in [label, playbook, *cells(rows.get((label, playbook)) or empty_row())]))
    print("== ALL_TIME (every Lead AI campaign message) ==")
    print("playbook\t" + "\t".join(COLUMNS))
    for playbook in (*PLAYBOOKS, TOTAL):
        print("\t".join(str(value) for value in [playbook, *cells(rows.get((ALL, playbook)) or empty_row())]))

    print("== CHECKS ==")
    counts = Counter(row[2] for row in recipients)
    print("recipients of Lead AI campaigns by status: " + " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(f"recipients whose phone is on the Lead AI test-number list (left out of every count): {testers}")
    listed = sorted(campaigns.items(), key=lambda item: item[1][2])
    per_campaign = Counter(row[1] for row in recipients)
    print("lead ai campaigns: " + (" | ".join(
        f"{cid} {pb} {made.astimezone(DUBAI):%Y-%m-%d} recipients={per_campaign[cid]}" for cid, (pb, _, made) in listed[-40:]
    ) or "none") + (f" (and {len(listed) - 40} older)" if len(listed) > 40 else ""))
    accepted_failed = sum(1 for send in sends if send["accepted"] and send["failed"])
    print(f"failed (all time): refused by the gateway {refused}, reported failed by Meta after sending {accepted_failed}; still due for a campaign retry {retry_due}")
    print(f"sent, no delivery report yet (all time): {in_flight}")
    print(f"campaign messages whose template message was not found (delivered/read unknown): {unmatched}")
    print(f"chats reached by a Lead AI campaign message (all time): {len(by_chat)}")
    print(f"replied chats whose other side is an automatic reply (all time, in replied): {len(auto_reply_chats)}")
    print(f"chats with a visit talked about but never confirmed (all time, not in booked): {len(tentative_chats)}")
    by_source = Counter(source for _, source in handover_sources)
    print("handover chats by source (all time): " + (" ".join(f"{k}={v}" for k, v in sorted(by_source.items())) or "none"))
    by_source = Counter(source for _, source in opt_out_sources)
    print("opt-out chats by source (all time; a chat can show in several): " + (" ".join(f"{k}={v}" for k, v in sorted(by_source.items())) or "none"))
    print(f"opt-out registry rows from the back-fill tied to these chats (not counted: they hold the back-fill's time): {backfilled}")
    print(f"campaign messages before {first_label} (in ALL_TIME only): {before}")


try:
    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
        probe()
        raise Rollback
except Rollback:
    pass
print("PROBE_OK")
