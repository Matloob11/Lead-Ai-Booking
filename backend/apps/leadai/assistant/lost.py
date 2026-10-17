"""A shops "no": Bot Status Lost always, the lost stage only for a lead nobody is working (launch review issue 1).

Live (launch 2026-10-15), every "not interested" lead went to Not Interested at once, and Bitrix completed the
open to-dos of seven agents in the same second (a lead moved to a lost stage has its open activities closed):
176882, 170807, 173045, 174899, 174029, 174011, 175279, some due 10-16 and 10-19. In five of those chats a
person was working the customer that day: chat 42's buyer with agent 2298 in another chat (Option Sent, budget
650,000), chat 120 with agent 2392 (74 messages from 11:18), and 52, 118 and 119 reopened by hand.

The default until Matloob decides (synth.json decisions_for_matloob), one constant each below:
- a shops "no" writes Bot Status Lost (2480), its timeline note and the alert to the lead's owner and the Lead
  AI alert list, every time (engine.record_opt_out);
- the move to Not Interested ("1") or Junk Lead ("JUNK") goes only when the lead, read through the Bitrix REST
  client just before it (tasks.write_crm_fields, may_move), shows that nobody worked it for TOUCH_WINDOW and it
  has no open activity at all: no to-do, call, meeting or task of anyone's, which the move would close. A read
  that fails moves nothing. So nobody's to-do is ever closed or changed: the stage moves only when there is none.
  A lead kept in its stage gets the customer's words and why on its timeline instead (kept_comment).

What counts as a person working the lead (any of them keeps it where it is):
- one of our colleagues wrote to this customer on WhatsApp, on any of our numbers, in TOUCH_WINDOW (inbox_touch:
  chats 42 and 120's agents worked them in chats the assistant never sees);
- a meeting on it (stage 10 or 11, or a Meeting Date & Time), a closed stage already, or a lead that came in
  less than NEW_LEAD ago (its agent's new inquiry);
- its stage moved, a field changed, or its last timeline activity, by a person in TOUCH_WINDOW (MOVED_BY_ID and
  MOVED_TIME, MODIFY_BY_ID and DATE_MODIFY, LAST_ACTIVITY_BY and LAST_ACTIVITY_TIME, when the portal gives them);
- an open activity, or one a person created or changed in TOUCH_WINDOW (a call, a to-do done, an e-mail);
- a timeline comment a person wrote in TOUCH_WINDOW (the lead guard's "Edited by" notes are the editor's own).
A person is any Bitrix user but SYSTEM_USERS (0, and 1: the Lead fields tool, BP 235, the robots and the admin
hold user) and the REST webhook's own user (our timeline mirror, the summaries).
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

from apps.crmlink import client

from . import crm, hours

logger = logging.getLogger(__name__)

# The move to a lost stage at all: False writes Bot Status Lost and the comment only, never the stage.
MOVE_STAGE = True
# A person who touched the lead in this long keeps it in its stage (Matloob's safe default, 2026-10-15).
TOUCH_WINDOW = dt.timedelta(days=7)
# A lead that came in this recently is its agent's new inquiry: never moved by a "no" to our shops offer.
NEW_LEAD = TOUCH_WINDOW
# Bitrix users whose edits are nobody working the lead: the Lead fields tool and the comments it posts (user 1),
# BP 235 and the robots, the admin hold user. The REST webhook's own user is added at run time (system_users).
SYSTEM_USERS = frozenset({"", "0", "1"})
# A lead with a meeting booked or held, or in a closed stage, is never moved.
MEETING_STAGES = {"10": "Meeting/Viewing Scheduled", "11": "Meeting/Viewing Done"}
CLOSED_STAGES = frozenset({"1", "JUNK", "9", "CONVERTED"})
STAGE_NAMES = {"1": "Not Interested", "JUNK": "Junk Lead"}
# The newest activities and comments read for a person's recent work (one REST page each).
PAGE = 50
NOT_MOVED = "Not moved: "
# A lost row whose lead sits in that stage already, a try of ours never having posted it.
ALREADY_THERE = "Not sent: the lead is in that stage already."
# The payload key a lost row gets once its kept comment is posted (tasks.write_crm_fields): never a second time.
KEPT_COMMENT = "kept_comment"


@dataclass(frozen=True)
class Decision:
    move: bool
    why: str = ""


def system_users() -> frozenset:
    """SYSTEM_USERS and the REST webhook's own user (…/rest/<user>/<token>/): what our own REST calls write."""
    found = re.search(r"/rest/(\d+)/", str(getattr(settings, "BITRIX_WEBHOOK_URL", "") or ""))
    return SYSTEM_USERS | ({found.group(1)} if found else set())


def when(value) -> dt.datetime | None:
    """A Bitrix date ("2026-10-15T10:30:43+04:00"), aware, else None."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.replace(tzinfo=hours.DUBAI) if timezone.is_naive(moment) else moment


def _day(moment: dt.datetime) -> str:
    return f"{moment.astimezone(hours.DUBAI):%d %b}"


def _user(value) -> str:
    return str(value or "").strip()


def _recent(moment, now) -> bool:
    return moment is not None and now - moment <= TOUCH_WINDOW


# Judging what was read (pure; tested) --------------------------------------------------------------------------


def judge_stage(lead: dict, now=None) -> str:
    """Why the lead is past the assistant, by its stage: closed already, a meeting stage, or a meeting time ('' for none).
    ``now``: a meeting time older than TOUCH_WINDOW then counts no more (a follow-up's reading: bitrix_blocks); without
    it, any meeting time counts (a move's: never move a lead with a meeting)."""
    lead = lead or {}
    stage = str(lead.get("STATUS_ID") or "")
    if stage in CLOSED_STAGES or str(lead.get("STATUS_SEMANTIC_ID") or "") in ("S", "F"):
        return f"it is in a closed stage already ({STAGE_NAMES.get(stage, stage or 'closed')})"
    if stage in MEETING_STAGES:
        return f"it has a meeting ({MEETING_STAGES[stage]})"
    meeting = str(lead.get(crm.FIELD_MEETING_AT) or "").strip()
    if meeting:
        at = when(meeting)
        if now is None or at is None or at >= now - TOUCH_WINDOW:
            return "it has a meeting time"
    return ""


def touch_of(lead: dict, now, system=SYSTEM_USERS) -> dict | None:
    """A person's own touch the lead's fields show in TOUCH_WINDOW (their stage move, change or last activity), as
    {"by", "at", "did"}, else None."""
    lead = lead or {}
    for by, at, did in (
        ("MOVED_BY_ID", "MOVED_TIME", "moved its stage"),
        ("MODIFY_BY_ID", "DATE_MODIFY", "changed it"),
        ("LAST_ACTIVITY_BY", "LAST_ACTIVITY_TIME", "worked on it"),
    ):
        user, moment = _user(lead.get(by)), when(lead.get(at))
        if user not in system and _recent(moment, now):
            return {"by": user, "at": moment.isoformat(), "did": did}
    return None


def judge_touch(lead: dict, now, system=SYSTEM_USERS) -> str:
    """Why: a person moved its stage, changed it or worked on it in TOUCH_WINDOW, by its own fields ('' for none)."""
    touch = touch_of(lead, now, system)
    return f"Bitrix user {touch['by']} {touch['did']} on {_day(when(touch['at']))}" if touch else ""


# A person's touch an earlier read of the lead saw (tasks.write_crm_fields keeps it on its rows, payload key): our own
# writes hide it on the lead afterwards, for the Lead fields tool and our timeline mirror write as user 1, so the lead's
# MODIFY_BY_ID and LAST_ACTIVITY_BY are ours after them (review 2d).
PERSON_TOUCH = "person_touch"


def remembered_touch(lead_id, now) -> str:
    """Why: a person's touch on the lead that an earlier read saw before a write of ours hid it, in TOUCH_WINDOW ('' for
    none)."""
    from ..models import LeadAiCrmField

    payloads = (
        LeadAiCrmField.objects.filter(lead_id=lead_id, payload__has_key=PERSON_TOUCH).order_by("-pk").values_list("payload", flat=True)[:20]
    )
    for payload in payloads:
        touch = (payload if isinstance(payload, dict) else {}).get(PERSON_TOUCH) or {}
        moment = when(touch.get("at"))
        if _recent(moment, now):
            return f"Bitrix user {touch.get('by')} {touch.get('did') or 'changed it'} on {_day(moment)}"
    return ""


def judge_lead(lead: dict, now, system=SYSTEM_USERS) -> str:
    """Why the lead stays in its stage, by its own fields ('' when they give no reason)."""
    lead = lead or {}
    why = judge_stage(lead)
    if why:
        return why
    created = when(lead.get("DATE_CREATE"))
    if created is not None and now - created < NEW_LEAD:
        return f"it came in on {_day(created)}, less than {NEW_LEAD.days} days ago"
    return judge_touch(lead, now, system)


def judge_open(rows) -> str:
    """Why: an open activity on the lead (any kind, anyone's), which the move would close."""
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or str(row.get("COMPLETED") or "N") == "Y":
            continue
        subject = " ".join(str(row.get("SUBJECT") or "").split())[:60] or "activity"
        owner = _user(row.get("RESPONSIBLE_ID"))
        return f"it has an open to-do ({subject}" + (f", Bitrix user {owner})" if owner else ")")
    return ""


# A call (2) or an e-mail (4) is a person's work with the customer whoever wrote it down: the 3CX click-to-call and the
# recordings sync write through the webhook of user 1, with the agent only in RESPONSIBLE_ID (review 2d).
WORK_TYPES = frozenset({"2", "4"})


def judge_activities(rows, now, system=SYSTEM_USERS) -> str:
    """Why: a person created or changed one of its activities in TOUCH_WINDOW (a call, a to-do done, an e-mail), or a
    call or e-mail of a person's (WORK_TYPES, RESPONSIBLE_ID) is that recent, whoever recorded it."""
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        subject = " ".join(str(row.get("SUBJECT") or "").split())[:60] or "an activity"
        for by, at in (("AUTHOR_ID", "CREATED"), ("EDITOR_ID", "LAST_UPDATED")):
            user, moment = _user(row.get(by)), when(row.get(at))
            if user not in system and _recent(moment, now):
                return f"Bitrix user {user} worked on it on {_day(moment)} ({subject})"
        if str(row.get("TYPE_ID") or "") in WORK_TYPES:
            owner = _user(row.get("RESPONSIBLE_ID"))
            moments = [
                moment for moment in (when(row.get(key)) for key in ("LAST_UPDATED", "CREATED", "END_TIME", "START_TIME"))
                if moment is not None and moment <= now and _recent(moment, now)
            ]
            if owner not in system and moments:
                what = "a call" if str(row.get("TYPE_ID")) == "2" else "an e-mail"
                return f"Bitrix user {owner} had {what} with the customer on {_day(max(moments))} ({subject})"
    return ""


def judge_comments(rows, now, system=SYSTEM_USERS) -> str:
    """Why: a person wrote a timeline comment in TOUCH_WINDOW (the lead guard's "Edited by" notes are the editor's)."""
    if isinstance(rows, dict):
        rows = rows.get("items")
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        user, moment = _user(row.get("AUTHOR_ID")), when(row.get("CREATED"))
        if user not in system and _recent(moment, now):
            return f"Bitrix user {user} wrote on its timeline on {_day(moment)}"
    return ""


# Reading ------------------------------------------------------------------------------------------------------


def read_lead(lead_id) -> dict | None:
    """The lead as Bitrix holds it now (crm.lead.get), or None when it cannot be read."""
    try:
        row = client.call("crm.lead.get", {"id": int(lead_id)})
    except client.BitrixError as exc:
        logger.info("Lead AI could not read lead %s before writing it: %s", lead_id, exc)
        return None
    return row if isinstance(row, dict) else None


def inbox_touch(phone: str, since) -> dt.datetime | None:
    """When one of our colleagues last wrote to this customer on WhatsApp since ``since``, on any of our numbers
    (the panel, the phone app, a template sent by hand), else None. Never ours (the Lead AI's, Sara's, the AI
    desk's), never a campaign's own template."""
    from apps.campaigns.models import CampaignRecipient
    from apps.crmlink.tasks import campaign_sends
    from apps.inbox.models import Message

    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if not digits:
        return None
    campaign_templates = (
        CampaignRecipient.objects.filter(phone=digits).exclude(campaign__template_id__isnull=True).values_list("campaign__template_id", flat=True)
    )
    rows = (
        Message.objects.filter(
            conversation__contact__wa_id=digits, direction=Message.Direction.OUTBOUND, created_at__gte=since, mirrored_from__isnull=True
        )
        .exclude(kind__in=("system", "reaction"))
        .exclude(campaign_sends())
        .exclude(kind=Message.Kind.TEMPLATE, template_id__in=campaign_templates)
        .order_by("-created_at")
        .only("pk", "payload", "created_at")
    )
    for row in rows[:200]:
        source = str((row.payload if isinstance(row.payload, dict) else {}).get("source") or "")
        if source.startswith(("leadai", "leadbot", "ai_desk")):
            continue
        return row.created_at
    return None


def may_move(lead_id, phone: str, *, now=None, lead: dict | None = None) -> Decision:
    """May a shops "no" move this lead to its lost stage now? Read through the Bitrix REST client (``lead``: read
    already), cheapest first, and stopping at the first reason it may not; any read that fails moves nothing."""
    now = now or timezone.now()
    if not MOVE_STAGE:
        return Decision(False, "the lost stage move is switched off (lost.MOVE_STAGE)")
    touched = inbox_touch(phone, now - TOUCH_WINDOW)
    if touched is not None:
        return Decision(False, f"a colleague wrote to the customer on WhatsApp on {_day(touched)}")
    if lead is None:
        lead = read_lead(lead_id)
    if lead is None:
        return Decision(False, "Bitrix could not be read")
    system = system_users()
    why = judge_lead(lead, now, system) or remembered_touch(lead_id, now)
    if why:
        return Decision(False, why)
    try:
        owner = {"OWNER_TYPE_ID": 1, "OWNER_ID": int(lead_id)}
        select = [
            "ID", "SUBJECT", "COMPLETED", "RESPONSIBLE_ID", "AUTHOR_ID", "EDITOR_ID", "CREATED", "LAST_UPDATED", "TYPE_ID", "PROVIDER_ID",
            "START_TIME", "END_TIME",
        ]
        why = judge_open(client.call("crm.activity.list", {"filter": {**owner, "COMPLETED": "N"}, "order": {"ID": "DESC"}, "select": select}))
        if why:
            return Decision(False, why)
        why = judge_activities(client.call("crm.activity.list", {"filter": owner, "order": {"ID": "DESC"}, "select": select}), now, system)
        if why:
            return Decision(False, why)
        comments = client.call(
            "crm.timeline.comment.list",
            {"filter": {"ENTITY_ID": int(lead_id), "ENTITY_TYPE": "lead"}, "select": ["ID", "CREATED", "AUTHOR_ID"], "order": {"ID": "DESC"}},
        )
        why = judge_comments(comments, now, system)
        if why:
            return Decision(False, why)
    except client.BitrixError as exc:
        logger.info("Lead AI could not read the activities of lead %s, so it is not moved: %s", lead_id, exc)
        return Decision(False, "Bitrix could not be read")
    return Decision(True, "")


def moved_already(lead: dict | None, stage: str) -> bool:
    """The lead as read sits in this lost stage with Bot Status Lost already: nothing is left to move (an earlier try of
    ours did it and its answer was lost, or a person did), and no "it was not moved" belongs on its timeline."""
    from . import crm_fields

    if not isinstance(lead, dict) or str(lead.get("STATUS_ID") or "") != str(stage or ""):
        return False
    status = lead.get(crm_fields.FIELD_BOT_STATUS)
    status = status[0] if isinstance(status, (list, tuple)) and status else status
    return str(status or "").strip() == str(crm_fields.STATUS_LOST)


def kept_comment(stage: str, reason: str, why: str) -> str:
    """The lead's timeline line when it stays in its stage (the Lead fields tool puts "Lead AI: " before it)."""
    words = crm.safe(reason)[:200] or ("no" if stage != "JUNK" else "wrong number")
    said = "The chat reads as a wrong number or spam" if stage == "JUNK" else "The customer said no to our shops offer"
    return (
        f"{said} ({words}). Bot Status is Lost; the lead was not moved to "
        f"{STAGE_NAMES.get(stage, stage)}, because {why}. No to-do was closed or changed."
    )[:1000]


def alert_lines(words: str, *, rented: bool = False) -> list[str]:
    """What the lead's owner and the Lead AI alert list read when a shops customer says no (engine.record_opt_out)."""
    said = crm.safe(words)[:200]
    return [
        ("They already rented a shop elsewhere, and said no to a second one." if rented else f"Their words: {said}") if (said or rented) else "",
        "Bot Status is now Lost in Bitrix, so no Lead AI campaign reaches them again.",
        f"The lead goes to Not Interested only if nobody from the team worked it in the last {TOUCH_WINDOW.days} days and it has "
        "no open to-do; otherwise it stays in its stage, and no to-do is closed or changed. If you are working this customer, "
        "carry on.",
    ]
