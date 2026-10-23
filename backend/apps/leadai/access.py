"""Who sees what of the Lead AI screen, per Bitrix user (Matloob 2026-10-23, round 25).

Three grants, each on its own (``LeadAiAccess``, keyed by the Bitrix user id as the handover desk is, so a grant made
before the person ever signed in holds from their first sign-in):

- ``all_chats``: every Lead AI chat on any number, its live feed and its alerts — the grant Agents & access calls Lead AI
  access (``Agent.can_lead_ai``). The two are kept in step: a change here writes the account's flag, a change there
  writes the row (``sync_from_agent``), and either one grants.
- ``today``: the Today list, every open visit and call of the day across every Lead AI chat, and those chats to open.
- ``needs``: the Needs a person list, every chat waiting for someone from the team, and those chats to open.

A panel admin sees everything whatever the rows say; an agent with none of the three keeps what they had: their own
chats, and their handovers on "My handovers" (handover_desk.py). The admin screen (bitrix/public/assets/modules/lead-ai/
access.js) lists the portal's users live (``bitrix_users``: user.get, the webhook's user scope) merged with the panel's
accounts, each with its grants, its handovers and whether it is an admin; the sign-in payload carries the effective
flags (``of``), and ``leadai.access.changed`` tells an agent's open panel when theirs change.

What the grants open is one clause, ``q_for``, which inbox.visibility OR-s into every agent's visibility through
lane.desk_q, so every inbox and Lead AI endpoint follows without a change (the Today and Needs a person lists are
views of the visible chats: desk.today_rows, desk.needs_rows).
"""

from __future__ import annotations

import logging
import time

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q, Subquery
from django.utils import timezone

from .assistant.alerts import HOLD_USERS
from .models import LeadAiAccess, LeadAiAppointment, LeadAiChat, LeadAiChatState

logger = logging.getLogger(__name__)

FLAGS = ("all_chats", "today", "needs")
# The portal's user list is read again this often at most (the shared Bitrix rate limit); ?refresh=1 reads it now.
USERS_CACHE_SECONDS = 60
USERS_PAGE = 50
USERS_MAX = 1000
CHANGED = "leadai.access.changed"
_users_cache: dict = {"at": 0.0, "read_at": None, "rows": [], "error": ""}


def bitrix_id(user) -> str:
    """The agent's Bitrix user id, digits only; "" for none and for the hold users (0 and 1)."""
    digits = "".join(ch for ch in str(getattr(user, "bitrix_user_id", "") or "") if ch.isdigit())
    return "" if digits in HOLD_USERS else digits


def row_for(bitrix_user_id: str) -> LeadAiAccess | None:
    if not bitrix_user_id:
        return None
    return LeadAiAccess.objects.filter(bitrix_user_id=str(bitrix_user_id)).first()


def nothing(admin: bool = False) -> dict:
    return {"admin": admin, "all_chats": admin, "today": admin, "needs": admin, "any": admin}


def of(user) -> dict:
    """The effective grants of a signed-in agent: {admin, all_chats, today, needs, any}. A panel admin has everything;
    an inactive agent, or one without the Official API inbox, nothing. Read once per request (memoised on the user)."""
    if user is None or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return nothing()
    if not getattr(user, "can_official_api", True):
        return nothing()
    cached = getattr(user, "_leadai_access", None)
    if cached is not None:
        return cached
    from apps.inbox.visibility import sees_all_inbox_chats

    if sees_all_inbox_chats(user):
        found = nothing(admin=True)
    else:
        row = row_for(bitrix_id(user))
        flag = bool(getattr(user, "can_lead_ai", False))
        if row is not None and row.all_chats and not flag and getattr(user, "pk", None):
            # A grant made before the account existed (the point of keying on the Bitrix id): the account's own flag
            # follows it the first time the account is seen, so Agents & access and the sign-in payload say the same.
            get_user_model().objects.filter(pk=user.pk, can_lead_ai=False).update(can_lead_ai=True)
            try:
                user.can_lead_ai = True
            except Exception:  # noqa: BLE001
                pass
            flag = True
        all_chats = flag or bool(row and row.all_chats)
        today = all_chats or bool(row and row.today)
        needs = all_chats or bool(row and row.needs)
        found = {"admin": False, "all_chats": all_chats, "today": today, "needs": needs, "any": all_chats or today or needs}
    try:
        user._leadai_access = found
    except Exception:  # noqa: BLE001 - a user object that takes no attribute: read again next time
        pass
    return found


def forget(user) -> None:
    """The memo dropped (a grant changed in the same request)."""
    if hasattr(user, "_leadai_access"):
        try:
            del user._leadai_access
        except Exception:  # noqa: BLE001
            pass


def active_q():
    return Q(pk__in=Subquery(LeadAiChat.objects.filter(active=True).values("conversation_id")))


def today_q(now=None):
    """The chats with an open visit or call that starts today, Dubai time (desk.today_rows lists them)."""
    from .desk import today_window

    start, end = today_window(now)
    booked = LeadAiAppointment.objects.filter(status__in=LeadAiAppointment.OPEN, starts_at__gte=start, starts_at__lt=end).values(
        "conversation_id"
    )
    return Q(pk__in=Subquery(booked))


def needs_q():
    """The chats the Needs a person list may show (desk.needs_rows reads them finer): handed over or paused for a broker
    (not stopped, not done), or with an open tentative visit; and a chat on someone's handover desk until Done
    (desk_at set, desk_done_at not), so the chat a granted agent answered stays with them while the assistant takes
    over again (handed_over_at clears the moment a person writes), until a person says it is done."""
    states = (
        LeadAiChatState.objects.filter(stopped_at__isnull=True, not_interested_at__isnull=True)
        .filter(
            Q(handed_over_at__isnull=False)
            | Q(paused_at__isnull=False, paused_by__isnull=True)
            | Q(desk_at__isnull=False, desk_done_at__isnull=True)
        )
        .values("conversation_id")
    )
    held = LeadAiAppointment.objects.filter(status=LeadAiAppointment.Status.TENTATIVE).values("conversation_id")
    return Q(pk__in=Subquery(states)) | Q(pk__in=Subquery(held))


def q_for(user, now=None):
    """inbox.visibility's clause for the grants (through lane.desk_q): every active Lead AI chat with all_chats, else
    the day's booked chats and the chats waiting for a person as granted; None for an agent with no grant (not even a
    query more) and for a panel admin (the inbox's own visibility is theirs)."""
    found = of(user)
    if found["admin"] or not found["any"]:
        return None
    if found["all_chats"]:
        return active_q()
    parts = []
    if found["today"]:
        parts.append(today_q(now))
    if found["needs"]:
        parts.append(needs_q())
    clause = parts[0]
    for part in parts[1:]:
        clause |= part
    return active_q() & clause


def event_groups(conversation) -> list[str]:
    """The live channels of the agents whose Today or Needs a person grant covers this chat (inbox.events.publish,
    through lane.desk_groups_for): they join no number group and not the desk's (lane.desk_groups), so the chat's
    frames go to their own channel, in full (a grant is the team's trust; nothing of the chat is trimmed for them).
    An agent with all_chats, the account's flag or the row's, hears the desk's group instead; a panel admin the
    number's; an inactive account, or one without the Official API inbox, nothing."""
    pk = getattr(conversation, "pk", None)
    if pk is None:
        return []
    rows = list(
        LeadAiAccess.objects.filter(all_chats=False).filter(Q(today=True) | Q(needs=True)).values_list("bitrix_user_id", "today", "needs")
    )
    if not rows:
        return []
    from apps.inbox.events import group_for_agent
    from apps.inbox.models import Conversation

    chat = Conversation.objects.filter(pk=pk).filter(active_q())
    in_today = chat.filter(today_q()).exists() if any(today for _, today, _ in rows) else False
    in_needs = chat.filter(needs_q()).exists() if any(needs for _, _, needs in rows) else False
    ids = [bitrix_user_id for bitrix_user_id, today, needs in rows if (today and in_today) or (needs and in_needs)]
    if not ids:
        return []
    agents = get_user_model().objects.filter(
        bitrix_user_id__in=ids, is_active=True, can_official_api=True, can_lead_ai=False, is_wa_admin=False, is_superuser=False
    )
    return [group_for_agent(agent_pk) for agent_pk in agents.order_by("pk").values_list("pk", flat=True)]


def ping_groups(conversation, covered: list[str]) -> list[str]:
    """The live channels of the Today / Needs a person agents the chat's frames do NOT go to (event_groups left them
    out: the chat is not in their lists now). They get an id-only "leadai.access.resync" instead (inbox.events.publish),
    so a chat that just left a list goes from their screen; nothing of the chat travels."""
    rows = LeadAiAccess.objects.filter(all_chats=False).filter(Q(today=True) | Q(needs=True)).values_list("bitrix_user_id", flat=True)
    ids = list(rows)
    if not ids:
        return []
    from apps.inbox.events import group_for_agent

    agents = get_user_model().objects.filter(
        bitrix_user_id__in=ids, is_active=True, can_official_api=True, can_lead_ai=False, is_wa_admin=False, is_superuser=False
    )
    return [group for group in (group_for_agent(pk) for pk in agents.order_by("pk").values_list("pk", flat=True)) if group not in covered]


def _agent_of(bitrix_user_id: str):
    return get_user_model().objects.filter(bitrix_user_id=str(bitrix_user_id)).order_by("pk").first()


def _record(row: LeadAiAccess, diff: dict, by) -> None:
    who = (getattr(by, "display_name", "") or getattr(by, "username", "") or str(by or "ops")) if by is not None else "ops"
    row.history = (list(row.history or []) + [{"at": timezone.now().isoformat(), "by": who, "changes": diff}])[-50:]
    if by is not None and getattr(by, "pk", None):
        row.updated_by = by


def payload_for(user) -> dict:
    """The sign-in payload's ``lead_ai_access`` (accounts.views) and the live event's: the effective grants."""
    found = of(user)
    return {flag: found[flag] for flag in ("admin", "all_chats", "today", "needs", "any")}


def tell(bitrix_user_id: str) -> None:
    """The agent's own live channel hears their grants changed, as they stand now for the account (effective, the
    shape the sign-in payload has: lead-ai.js takes it as is), after the commit; the socket reads its groups again."""
    agent = _agent_of(bitrix_user_id)
    if agent is None:
        return
    found = payload_for(agent)  # a fresh instance: no memo, the flag as grant() left it

    def publish():
        from apps.inbox.events import publish_to_agent

        publish_to_agent(agent.pk, CHANGED, {"access": found})

    transaction.on_commit(publish)


def grant(bitrix_user_id: str, changes: dict, by=None) -> LeadAiAccess:
    """Set the grants named in ``changes`` (FLAGS, as booleans) for this Bitrix user; the account's Lead AI access flag
    (Agent.can_lead_ai) follows all_chats; the change is recorded on the row and told to the agent's panel."""
    bitrix_user_id = "".join(ch for ch in str(bitrix_user_id or "") if ch.isdigit())
    if not bitrix_user_id or bitrix_user_id in HOLD_USERS:
        raise ValueError("a Bitrix user id is needed (not a hold user)")
    with transaction.atomic():
        row, _ = LeadAiAccess.objects.select_for_update().get_or_create(bitrix_user_id=bitrix_user_id)
        accounts = get_user_model().objects.filter(bitrix_user_id=bitrix_user_id)
        before = row.flags()
        # The grant as it stands is the row's or the account's own flag (Agents & access, before this screen existed,
        # or a row the account has not been seen with yet): a revoke must clear both, and a Today change alone must
        # not read as a revoke.
        before["all_chats"] = before["all_chats"] or accounts.filter(can_lead_ai=True).exists()
        wanted = {**before, **{flag: bool(changes[flag]) for flag in FLAGS if flag in changes}}
        diff = {flag: [before[flag], wanted[flag]] for flag in FLAGS if before[flag] != wanted[flag]}
        dirty = any(getattr(row, flag) != wanted[flag] for flag in FLAGS)
        for flag in FLAGS:
            setattr(row, flag, wanted[flag])
        if diff:
            _record(row, diff, by)
        if diff or dirty:
            row.save()
        accounts.exclude(can_lead_ai=wanted["all_chats"]).update(can_lead_ai=wanted["all_chats"])
        if diff:
            tell(bitrix_user_id)
    return row


def sync_from_agent(agent) -> None:
    """Agents & access changed Agent.can_lead_ai (catalog.views): the row's all_chats follows, so the two never disagree."""
    bitrix_user_id = bitrix_id(agent)
    if not bitrix_user_id:
        return
    wanted = bool(getattr(agent, "can_lead_ai", False))
    row, _ = LeadAiAccess.objects.get_or_create(bitrix_user_id=bitrix_user_id)
    if row.all_chats != wanted:
        _record(row, {"all_chats": [row.all_chats, wanted]}, None)
        row.all_chats = wanted
        row.save()
        tell(bitrix_user_id)


def bitrix_users(refresh: bool = False) -> list[dict]:
    """The portal's active users (user.get, paged), each {bitrix_user_id, name, position, email}; read again at most
    every USERS_CACHE_SECONDS (``refresh`` reads now). [] when no webhook is configured; the last list, when the portal
    cannot answer now (the state says so: bitrix_state)."""
    from apps.crmlink import client

    now = time.monotonic()
    if not refresh and _users_cache["rows"] and now - _users_cache["at"] < USERS_CACHE_SECONDS:
        return list(_users_cache["rows"])
    if not client.configured():
        _users_cache.update(at=now, error="no Bitrix webhook is configured")
        return []
    rows, start = [], 0
    try:
        while True:
            page = client.call("user.get", {"ACTIVE": True, "start": start}) or []
            if not isinstance(page, list):
                break
            for user in page:
                if not isinstance(user, dict) or not str(user.get("ID") or "").isdigit():
                    continue
                rows.append(
                    {
                        "bitrix_user_id": str(user.get("ID")),
                        "name": " ".join(f"{user.get('NAME') or ''} {user.get('LAST_NAME') or ''}".split()),
                        "position": str(user.get("WORK_POSITION") or "").strip(),
                        "email": str(user.get("EMAIL") or "").strip(),
                    }
                )
            if len(page) < USERS_PAGE or start + USERS_PAGE >= USERS_MAX:
                break
            start += USERS_PAGE
    except client.BitrixError as exc:
        logger.info("Lead AI access could not read the Bitrix users: %s", exc)
        _users_cache.update(at=now, error=str(exc)[:200])
        return list(_users_cache["rows"])
    _users_cache.update(at=now, read_at=timezone.now(), rows=rows, error="")
    return list(rows)


def bitrix_state() -> dict:
    """When the portal's list was read, and what went wrong when it could not be (the admin screen's line)."""
    read_at = _users_cache.get("read_at")
    return {"read_at": read_at.isoformat() if read_at else None, "error": _users_cache.get("error") or "", "users": len(_users_cache["rows"])}


def handover_counts() -> dict:
    """{Bitrix user id: chats on their handover desk}."""
    rows = (
        LeadAiChatState.objects.filter(desk_at__isnull=False, conversation__lead_ai_chat__active=True)
        .exclude(responsible_bitrix_user_id="")
        .values("responsible_bitrix_user_id")
        .annotate(n=Count("pk"))
    )
    return {row["responsible_bitrix_user_id"]: row["n"] for row in rows}


def _account_part(agent) -> dict | None:
    if agent is None:
        return None
    from apps.inbox.visibility import sees_all_inbox_chats

    # "admin" here is the one of() and every Lead AI endpoint mean, a panel admin (sees_all_inbox_chats); a Bitrix
    # portal admin who is no panel admin sees nothing of Lead AI but their grants, and gets switches like anyone.
    admin = bool(sees_all_inbox_chats(agent))
    return {
        "id": agent.pk,
        "display_name": agent.display_name or agent.get_username(),
        "is_active": bool(agent.is_active),
        "can_official_api": bool(getattr(agent, "can_official_api", True)),
        "is_wa_admin": admin,
        "last_login": agent.last_login.isoformat() if agent.last_login else None,
    }


def _row(bitrix_user_id: str, user: dict | None, agent, row: LeadAiAccess | None, handovers: int) -> dict:
    flags = row.flags() if row is not None else {flag: False for flag in FLAGS}
    if agent is not None and getattr(agent, "can_lead_ai", False):
        flags["all_chats"] = True
    account = _account_part(agent)
    admin = bool(account and account["is_wa_admin"])
    usable = account is None or (account["is_active"] and account["can_official_api"])
    effective = {
        "all_chats": admin or flags["all_chats"],
        "today": admin or flags["all_chats"] or flags["today"],
        "needs": admin or flags["all_chats"] or flags["needs"],
    }
    if not usable:
        effective = {flag: False for flag in FLAGS}
    return {
        "bitrix_user_id": bitrix_user_id,
        "name": (user or {}).get("name") or (account or {}).get("display_name") or f"Bitrix user {bitrix_user_id}",
        "position": (user or {}).get("position", ""),
        "in_bitrix": user is not None,
        "account": account,
        "admin": admin,
        "access": flags,
        "effective": effective,
        "handovers": int(handovers or 0),
    }


def rows(refresh: bool = False) -> list[dict]:
    """The admin screen's list: every active Bitrix user (live) and every panel account with a Bitrix id, merged by that
    id (the hold users left out), the admins first, then by name."""
    users = {user["bitrix_user_id"]: user for user in bitrix_users(refresh)}
    agents = {
        bitrix_id(agent): agent
        for agent in get_user_model().objects.exclude(bitrix_user_id__isnull=True).exclude(bitrix_user_id="").order_by("pk")
        if bitrix_id(agent)
    }
    found = {row.bitrix_user_id: row for row in LeadAiAccess.objects.all()}
    counts = handover_counts()
    ids = (set(users) | set(agents)) - set(HOLD_USERS)
    out = [_row(pk, users.get(pk), agents.get(pk), found.get(pk), counts.get(pk, 0)) for pk in ids]
    out.sort(key=lambda item: (not item["admin"], item["name"].lower(), item["bitrix_user_id"]))
    return out


def row(bitrix_user_id: str) -> dict:
    """One user's row, as rows() shapes it (the answer to a grant)."""
    bitrix_user_id = str(bitrix_user_id)
    users = {user["bitrix_user_id"]: user for user in bitrix_users()}
    return _row(bitrix_user_id, users.get(bitrix_user_id), _agent_of(bitrix_user_id), row_for(bitrix_user_id), handover_counts().get(bitrix_user_id, 0))
