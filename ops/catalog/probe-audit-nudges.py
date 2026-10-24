"""Read-only: why nudge_1 did/didn't go for the audit's quiet chats.

Prints blocked(), bitrix_blocks(), last outbound status, open appointments,
and nudge_due for chats 54298, 54328, 54474, 54507, 54618. Nothing is sent.
"""

from django.utils import timezone

from apps.inbox.models import Conversation, Message
from apps.leadai import followups
from apps.leadai.models import LeadAiAppointment, LeadAiChat, LeadAiChatState, LeadAiSettings

CHATS = (54298, 54328, 54474, 54507, 54618)
settings_row = LeadAiSettings.load()
now = timezone.now()

for pk in CHATS:
    conversation = Conversation.objects.select_related("contact", "number").filter(pk=pk).first()
    if conversation is None:
        print(f"chat={pk} MISSING")
        continue
    chat = LeadAiChat.objects.filter(conversation=conversation).first()
    state = LeadAiChatState.objects.filter(conversation=conversation).first()
    last = (
        Message.objects.filter(conversation=conversation, direction=Message.Direction.OUTBOUND)
        .exclude(kind=Message.Kind.SYSTEM)
        .order_by("-pk")
        .first()
    )
    last_status = last.status if last else "-"
    last_id = last.pk if last else None
    last_at = last.created_at.isoformat() if last else None
    blocked = followups.blocked(conversation, chat, state, settings_row)
    bitrix = ""
    try:
        bitrix = followups.bitrix_blocks(
            conversation, chat, (state.facts if state is not None else None) or {}
        )
    except Exception as exc:  # noqa: BLE001
        bitrix = f"ERROR {exc}"
    due = followups.nudge_due(conversation, state, now, settings_row)
    open_appts = list(
        LeadAiAppointment.objects.filter(
            conversation=conversation, status__in=LeadAiAppointment.OPEN
        ).values_list("id", "status", "starts_at", "customer_words")[:5]
    )
    print(
        f"chat={pk} last_out={last_id} status={last_status} at={last_at} "
        f"blocked={blocked!r} bitrix_blocks={bitrix!r} nudge_due={due!r} "
        f"open_appts={open_appts} active={getattr(chat, 'active', None)} "
        f"stopped={getattr(state, 'stopped_at', None)} "
        f"handed={getattr(state, 'handed_over_at', None)} "
        f"paused={getattr(state, 'paused_at', None)}"
    )
print("PROBE_DONE")
