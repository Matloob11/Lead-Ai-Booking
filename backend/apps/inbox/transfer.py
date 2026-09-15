"""Official-number handover: panel copy, live mirror, customer sees a new chat.

WhatsApp keeps one thread per (our number, customer). Transfer therefore opens
(or reuses) the receiving agent's own Official number, copies history into the
panel only, and mirrors later messages both ways. Nothing copied here is sent
through the gateway.
"""

from django.utils import timezone

from apps.catalog.models import NumberAssignment

from .events import publish_conversation, publish_message, publish_to_agent
from .models import AssignmentLog, Conversation, Label, Message

TRANSFERRED_LABEL = "Transferred"
TRANSFERRED_COLOUR = "#c9a227"


def official_number_for(agent):
    """The number new WhatsApp messages from this agent should leave from."""
    if agent is None:
        return None
    rows = (
        NumberAssignment.objects.filter(agent=agent, is_active=True, number__is_active=True)
        .select_related("number")
        .order_by("id")
    )
    primary = next((row for row in rows if row.role == NumberAssignment.Role.PRIMARY), None)
    row = primary or rows.first()
    return row.number if row else None


def transferred_label():
    label, _ = Label.objects.get_or_create(
        name=TRANSFERRED_LABEL, defaults={"colour": TRANSFERRED_COLOUR}
    )
    if label.colour != TRANSFERRED_COLOUR:
        label.colour = TRANSFERRED_COLOUR
        label.save(update_fields=["colour"])
    return label


def _unlink_peer(conversation):
    peer_id = conversation.linked_conversation_id
    if not peer_id:
        return
    Conversation.objects.filter(pk=peer_id, linked_conversation_id=conversation.pk).update(
        linked_conversation=None
    )
    conversation.linked_conversation = None
    conversation.save(update_fields=["linked_conversation"])


def _link(left, right):
    if left.pk == right.pk:
        return
    if left.linked_conversation_id and left.linked_conversation_id != right.pk:
        _unlink_peer(left)
    if right.linked_conversation_id and right.linked_conversation_id != left.pk:
        _unlink_peer(right)
    left.linked_conversation = right
    right.linked_conversation = left
    left.save(update_fields=["linked_conversation"])
    right.save(update_fields=["linked_conversation"])


def _copy_history(source, target):
    """Duplicate source messages onto target. No gateway calls, no wamids."""
    already = set(
        Message.objects.filter(conversation=target, mirrored_from_id__isnull=False).values_list(
            "mirrored_from_id", flat=True
        )
    )
    copies = []
    for msg in (
        source.messages.filter(mirrored_from__isnull=True)
        .exclude(kind=Message.Kind.SYSTEM)
        .order_by("created_at", "id")
        .iterator()
    ):
        if msg.pk in already:
            continue
        copies.append(
            Message(
                conversation=target,
                direction=msg.direction,
                kind=msg.kind,
                body=msg.body,
                media=msg.media,
                template=msg.template,
                payload={**(msg.payload or {}), "panel_copy": True},
                reactions=msg.reactions or {},
                is_starred=False,
                status=(
                    Message.Status.SENT
                    if msg.status == Message.Status.QUEUED
                    else msg.status
                ),
                sent_by=msg.sent_by,
                created_at=msg.created_at,
                mirrored_from=msg,
            )
        )
    if copies:
        Message.objects.bulk_create(copies, batch_size=200)

    last = target.messages.exclude(kind=Message.Kind.SYSTEM).order_by("-created_at", "-id").first()
    if last:
        target.last_message_at = last.created_at
        target.last_message_preview = (last.body or f"[{last.kind}]")[:255]
        target.last_message_kind = last.kind
        target.save(update_fields=["last_message_at", "last_message_preview", "last_message_kind"])


def _system_note(conversation, body):
    return Message.objects.create(
        conversation=conversation,
        direction=Message.Direction.OUTBOUND,
        kind=Message.Kind.SYSTEM,
        body=body,
        status=Message.Status.SENT,
        payload={"panel_copy": True},
        created_at=timezone.now(),
    )


def mirror_to_peer(message):
    """Copy a real WhatsApp message onto the linked Official thread, panel only."""
    if not message or message.mirrored_from_id:
        return None
    if message.kind == Message.Kind.SYSTEM:
        return None

    peer_id = (
        Conversation.objects.filter(pk=message.conversation_id)
        .values_list("linked_conversation_id", flat=True)
        .first()
    )
    if not peer_id:
        return None
    if Message.objects.filter(conversation_id=peer_id, mirrored_from=message).exists():
        return None

    copy = Message.objects.create(
        conversation_id=peer_id,
        direction=message.direction,
        kind=message.kind,
        body=message.body,
        media_id=message.media_id,
        template_id=message.template_id,
        payload={**(message.payload or {}), "panel_copy": True},
        reactions=message.reactions or {},
        status=(
            Message.Status.SENT
            if message.status == Message.Status.QUEUED
            else message.status
        ),
        sent_by_id=message.sent_by_id,
        created_at=message.created_at,
        mirrored_from=message,
    )

    peer = Conversation.objects.select_related("contact", "number", "assigned_agent").get(pk=peer_id)
    peer.last_message_at = message.created_at or timezone.now()
    peer.last_message_preview = (message.body or f"[{message.kind}]")[:255]
    peer.last_message_kind = message.kind
    fields = ["last_message_at", "last_message_preview", "last_message_kind"]
    if message.direction == Message.Direction.INBOUND:
        peer.unread_count = peer.unread_count + 1
        fields.append("unread_count")
    peer.save(update_fields=fields)

    publish_message(copy)
    publish_conversation(peer)
    return copy


def apply_handover(conversation, to_agent, changed_by, reason=""):
    """Keep the source thread, copy it onto the receiving agent's Official number."""
    from .services import SendBlocked

    previous = conversation.assigned_agent

    if to_agent is None:
        conversation.assigned_agent = None
        conversation.save(update_fields=["assigned_agent"])
        AssignmentLog.objects.create(
            conversation=conversation,
            from_agent=previous,
            to_agent=None,
            changed_by=changed_by,
            reason=reason,
        )
        conversation = Conversation.objects.select_related(
            "contact", "number", "assigned_agent", "linked_conversation__number"
        ).get(pk=conversation.pk)
        publish_conversation(conversation, "conversation.assigned")
        return conversation

    target_number = official_number_for(to_agent)
    if target_number is None:
        raise SendBlocked(
            f"{to_agent.display_name or to_agent.username} has no Official number, so this chat cannot be copied onto theirs."
        )

    target, _ = Conversation.objects.get_or_create(
        number=target_number,
        contact=conversation.contact,
        defaults={"assigned_agent": to_agent},
    )
    target.assigned_agent = to_agent
    target.is_archived = False
    target.save(update_fields=["assigned_agent", "is_archived"])

    if target.pk != conversation.pk:
        _copy_history(conversation, target)
        _link(conversation, target)

    label = transferred_label()
    conversation.labels.add(label)
    target.labels.add(label)

    from_name = (previous.display_name if previous else None) or (
        changed_by.display_name if changed_by else "an agent"
    )
    to_name = to_agent.display_name or to_agent.username
    by_name = (changed_by.display_name if changed_by else None) or "an admin"
    note = (
        f"Transferred from {from_name} to {to_name} by {by_name}. "
        "History is a panel copy — the customer was not sent these messages again. "
        "New WhatsApp messages use each agent's own Official number. "
        f"{to_name} must send a template until the customer replies on that number."
    )
    if reason:
        note = f"{note} Reason: {reason}"
    src_note = _system_note(conversation, note)
    if target.pk != conversation.pk:
        _system_note(target, note)
    publish_message(src_note)

    AssignmentLog.objects.create(
        conversation=conversation,
        from_agent=previous,
        to_agent=to_agent,
        changed_by=changed_by,
        reason=reason,
    )
    if target.pk != conversation.pk:
        AssignmentLog.objects.create(
            conversation=target,
            from_agent=previous,
            to_agent=to_agent,
            changed_by=changed_by,
            reason=reason,
        )

    conversation = Conversation.objects.select_related(
        "contact", "number", "assigned_agent", "linked_conversation__number"
    ).get(pk=conversation.pk)
    target = Conversation.objects.select_related(
        "contact", "number", "assigned_agent", "linked_conversation__number"
    ).get(pk=target.pk)

    publish_conversation(conversation, "conversation.assigned")
    publish_conversation(target, "conversation.assigned")
    from .serializers import serialize_conversation

    publish_to_agent(
        to_agent.pk,
        "conversation.assigned",
        {"conversation": serialize_conversation(target)},
    )
    if changed_by is not None:
        publish_to_agent(
            changed_by.pk,
            "conversation.assigned",
            {"conversation": serialize_conversation(conversation)},
        )
    return target
