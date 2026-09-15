"""Where a number lives in the CRM, answered once for the panel.

The panel could ask Bitrix itself — it runs inside the portal and has BX24 —
but the answer now takes several REST calls: the duplicate search for leads,
another for contacts, a read of each candidate to reject the phone-list record,
and two filtered queries against Owner Data. Doing that from the browser on
every click would be slow and would repeat logic that already exists here, in
the one place that also has to get it right for the background mirror.
"""

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from . import client

# What the portal calls each record in a URL, so the panel can open one without
# knowing anything about Bitrix's naming.
PATHS = {
    "lead": "/crm/lead/details/{id}/",
    "contact": "/crm/contact/details/{id}/",
    f"DYNAMIC_{client.OWNER_DATA_TYPE_ID}": f"/crm/type/{client.OWNER_DATA_TYPE_ID}/details/{{id}}/",
}

LABELS = {
    "lead": "Lead",
    "contact": "Contact",
    f"DYNAMIC_{client.OWNER_DATA_TYPE_ID}": "Owner Data",
}


@api_view(["GET"])
def whereis(request):
    """GET /api/crm/whereis/?phone= — every CRM record carrying this number."""
    phone = request.GET.get("phone", "")
    if not client.configured():
        return Response({"records": [], "detail": "No CRM connection is configured."})

    records = client.find_records(phone)
    return Response(
        {
            "phone": "".join(ch for ch in phone if ch.isdigit()),
            "records": [
                {
                    "type": record["type"],
                    "id": record["id"],
                    "label": LABELS.get(record["type"], record["type"]),
                    "path": PATHS.get(record["type"], "").format(id=record["id"]),
                }
                for record in records
                if PATHS.get(record["type"])
            ],
        }
    )


@api_view(["POST"])
def create(request):
    """POST /api/crm/create/ — make the record this number has not got yet.

    ``{conversation: <id>, where: "lead" | "owner_data"}``

    The whole conversation is written into the new record's timeline straight
    away, oldest first, so an agent who has been talking to somebody for a week
    does not open a lead that claims the story starts now.

    Refuses when the number is already somewhere. Two leads for one customer is
    the exact problem this portal already has — a second one created from here
    would be our own doing.
    """
    from apps.inbox.models import Conversation, Message

    from .models import Mirror
    from .tasks import _line

    if not client.configured():
        return Response(
            {"detail": "No CRM connection is configured."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    conversation_id = request.data.get("conversation")
    where = str(request.data.get("where") or "").strip()

    if where not in ("lead", "owner_data"):
        return Response(
            {"detail": "where must be 'lead' or 'owner_data'."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    conversation = (
        Conversation.objects.filter(pk=conversation_id)
        .select_related("contact")
        .first()
    )
    if not conversation:
        return Response({"detail": "No such conversation."}, status=status.HTTP_404_NOT_FOUND)

    # Only on chats the caller can actually open, so this cannot be used to
    # create a record — and copy a conversation into it — for somebody else's
    # customer by guessing at ids.
    if not request.user.has_admin_rights:
        visible = request.user.visible_numbers.values_list("pk", flat=True)
        if conversation.number_id not in set(visible):
            return Response({"detail": "Not your conversation."}, status=status.HTTP_404_NOT_FOUND)

    wa_id = conversation.contact.wa_id
    existing = client.find_records(wa_id)
    if existing:
        return Response(
            {
                "detail": "This number is already in the CRM.",
                "records": [{"type": r["type"], "id": r["id"]} for r in existing],
            },
            status=status.HTTP_409_CONFLICT,
        )

    # `display_name` is what somebody typed for this person here; `profile_name`
    # is whatever WhatsApp reports, which is often a shop's own advertising.
    # Ours first, theirs as the fallback, the number if neither.
    contact = conversation.contact
    name = (contact.display_name or contact.profile_name or "").strip()
    try:
        record = (
            client.create_lead(wa_id, name)
            if where == "lead"
            else client.create_owner_data(wa_id, name)
        )
    except client.BitrixError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    # Oldest first, so the timeline reads in the order the conversation
    # happened rather than backwards.
    messages = list(
        Message.objects.filter(conversation=conversation)
        .select_related("sent_by")
        .order_by("created_at", "id")
    )

    copied = failed = 0
    for message in messages:
        try:
            comment_id = client.add_comment(record["type"], record["id"], _line(message))
        except client.BitrixError:
            # Kept going. A record holding most of the conversation is worth
            # more than one abandoned halfway, and Mirror records exactly what
            # did land so a later run finishes the job without duplicating.
            failed += 1
            continue
        Mirror.objects.get_or_create(
            message_id=message.pk,
            entity_type=record["type"],
            entity_id=record["id"],
            defaults={"comment_id": comment_id if isinstance(comment_id, int) else None},
        )
        copied += 1

    return Response(
        {
            "type": record["type"],
            "id": record["id"],
            "label": LABELS.get(record["type"], record["type"]),
            "path": PATHS.get(record["type"], "").format(id=record["id"]),
            "messages_copied": copied,
            "messages_failed": failed,
        }
    )
