# Run through `ops/wa.sh probe-lead-ai-fixture`: creates ONE synthetic Lead AI
# chat for a browser test of the Lead AI screen, and nothing else.
#   customer: wa_id 999000000001, named "ZZ Lead AI test (delete)" (not a phone)
#   number:   971524077268, owned by the agent of Bitrix user 2311
#   messages: one inbound, one outbound, made with bulk_create, so no message
#             signal runs (no Sara, no AI desk, no CRM mirror, no live event)
#   window:   closed, so the screen offers only "Send template"; nothing is sent
# Remove it with `ops/wa.sh probe-lead-ai-cleanup`. Idempotent.
from django.utils import timezone

from apps.accounts.models import Agent
from apps.catalog.models import WabaNumber
from apps.inbox.models import Contact, Conversation, Message
from apps.leadai.models import LeadAiChat

WA_ID = "999000000001"
NAME = "ZZ Lead AI test (delete)"

agent = Agent.objects.get(bitrix_user_id="2311", is_active=True)
number = WabaNumber.objects.get(phone_number="971524077268")
contact, _ = Contact.objects.get_or_create(wa_id=WA_ID, defaults={"display_name": NAME})
if contact.display_name != NAME:
    contact.display_name = NAME
    contact.save(update_fields=["display_name"])

now = timezone.now()
conversation, created = Conversation.objects.get_or_create(
    number=number, contact=contact, defaults={"assigned_agent": agent}
)
if created:
    Message.objects.bulk_create(
        [
            Message(
                conversation=conversation,
                direction=Message.Direction.OUTBOUND,
                kind=Message.Kind.TEXT,
                body="Lead AI test: this is the campaign message the customer received.",
                status=Message.Status.DELIVERED,
                sent_by=agent,
                created_at=now - timezone.timedelta(minutes=6),
            ),
            Message(
                conversation=conversation,
                direction=Message.Direction.INBOUND,
                kind=Message.Kind.TEXT,
                body="Lead AI test: the customer's reply. Is the villa still available?",
                status=Message.Status.DELIVERED,
                created_at=now - timezone.timedelta(minutes=5),
            ),
        ]
    )
Conversation.objects.filter(pk=conversation.pk).update(
    assigned_agent=agent,
    last_message_at=now - timezone.timedelta(minutes=5),
    last_message_preview="Lead AI test: the customer's reply. Is the villa still available?",
    last_message_kind="text",
    last_inbound_at=now - timezone.timedelta(days=2),
    session_expires_at=now - timezone.timedelta(days=1),
    unread_count=1,
)
chat, _ = LeadAiChat.objects.update_or_create(
    conversation=conversation,
    defaults={"active": True, "confirmed": True, "added_by": agent, "crm_entity": "lead", "crm_id": None,
              "moved_by": None, "moved_at": None},
)
print("FIXTURE conversation_id", conversation.pk, "created" if created else "existed", "| agent", agent.username,
      "| lead_ai active", chat.active)
print("PROBE_OK")
