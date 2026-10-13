"""Which Official numbers the gateway has recently refused.

Alots answers ``Network Banned`` on a From-number that cannot send. The panel
needs that on the number itself — otherwise New Contact defaults to the banned
line and hides the From picker under a scroll of templates.
"""

from datetime import timedelta

from django.db.models import Exists, OuterRef
from django.utils import timezone

from .models import Message

BLOCK_WINDOW = timedelta(days=14)


def with_send_health(queryset):
    """Annotate ``_send_blocked`` from recent failed template sends."""
    since = timezone.now() - BLOCK_WINDOW
    banned = Message.objects.filter(
        conversation__number_id=OuterRef("pk"),
        status=Message.Status.FAILED,
        kind=Message.Kind.TEMPLATE,
        created_at__gte=since,
        error_detail__icontains="network banned",
    )
    return queryset.annotate(_send_blocked=Exists(banned))
