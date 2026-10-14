"""Back-fill the WhatsApp opt-out registry from what customers already said (board T60, Q8).

    python manage.py leadai_optout_import --dry-run   count and show, store nothing
    python manage.py leadai_optout_import             add them

The same rules as every new message (signals._record_opt_out, optout.counts): a tap on
Unsubscribe, Stop, Stop messages or Stop promotions in any chat; a STOP or a wrong number
typed; and the words that are as often something else outside a Lead AI chat ("الغاء",
"block", "band karo") only as the answer to a campaign's template. In a chat on the Lead
AI screen, what the customer typed after it came onto the screen was the assistant's to
judge (it reads the whole burst and knows "cancel" for a booked visit), so there its own
record counts: a chat state stopped for a STOP, a wrong number or spam. What they typed
before, and everything in a chat since transferred to another agent (no turn reads
those), is judged like any other chat's. A phone already in the registry is left as it is.

The dry run says, for each way a phone asked us to stop (tapped, typed, typed as the answer
to a campaign, wrong number, a Lead AI chat stopped), how many and a few examples, so a
person can judge before the real run. Every row the real run adds says which, in its reason.

On the live server: `ops/wa.sh leadai-optout-import [--dry-run]`.
"""

from collections import Counter, defaultdict

from django.core.management.base import BaseCommand

from apps.inbox.models import Message
from apps.leadai import optout
from apps.leadai.assistant import rules
from apps.leadai.models import LeadAiChat, LeadAiChatState, LeadAiOptOut

TAPPED = "Tapped"
TYPED = "Typed"
CAMPAIGN_ANSWER = "Typed, answering a campaign"
WRONG_NUMBER = "Wrong number"
LEAD_AI = "Lead AI"
ORDER = (TAPPED, TYPED, CAMPAIGN_ANSWER, WRONG_NUMBER, LEAD_AI)
EXAMPLES = 3


class _Row:
    """What optout reads of a message, without loading its webhook payload."""

    __slots__ = ("pk", "conversation_id", "direction", "kind", "body", "payload")

    def __init__(self, pk, conversation_id, kind, body):
        self.pk = pk
        self.conversation_id = conversation_id
        self.direction = "in"
        self.kind = kind
        self.body = body
        # Ingest stores a tap's label as its body, so the label is read from there.
        self.payload = {}


def _how(row, stop: str) -> str:
    if optout.is_tap(row):
        return TAPPED
    if stop == rules.WRONG_NUMBER:
        return WRONG_NUMBER
    return CAMPAIGN_ANSWER if optout.ambiguous(row) else TYPED


class Command(BaseCommand):
    help = "Add the customers who already asked us to stop to the Lead AI opt-out registry."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Count and show, store nothing.")

    def handle(self, *args, dry_run, **options):
        # The chats on the Lead AI screen: since when, and whether transferred to another agent since.
        chats = {
            conversation_id: (since, bool(linked))
            for conversation_id, since, linked in LeadAiChat.objects.filter(active=True).values_list(
                "conversation_id", "created_at", "conversation__linked_conversation_id"
            )
        }
        found: dict[str, tuple] = {}  # phone -> (how, reason, conversation id), the newest kept
        scanned = 0
        rows = (
            Message.objects.filter(direction=Message.Direction.INBOUND, kind__in=("text", "button", "interactive"), mirrored_from__isnull=True)
            .order_by("pk")
            .values_list("pk", "kind", "body", "conversation_id", "conversation__contact__wa_id", "created_at")
        )
        for pk, kind, body, conversation_id, wa_id, created_at in rows.iterator(chunk_size=2000):
            scanned += 1
            row = _Row(pk, conversation_id, kind, body)
            stop = optout.message_opt_out(row)
            if not stop:
                continue
            chat = chats.get(conversation_id)
            if chat is not None and not optout.is_tap(row):
                since, transferred = chat
                if not transferred and created_at >= since:
                    continue  # the assistant's turn judged it; its own record counts (below)
            if optout.ambiguous(row) and not optout.answers_campaign(row):
                continue  # "الغاء" to a colleague's or a reminder's message: most likely "cancel"
            phone = optout.canonical(wa_id)
            if phone:
                found[phone] = (_how(row, stop), body, conversation_id)
        states = LeadAiChatState.objects.filter(stopped_at__isnull=False, stop_reason__in=list(STATE_SOURCES)).values_list(
            "stop_reason", "conversation_id", "conversation__contact__wa_id"
        )
        for reason, conversation_id, wa_id in states:
            phone = optout.canonical(wa_id)
            if phone:
                found[phone] = (LEAD_AI, LeadAiChatState.StopReason(reason).label, conversation_id)
        known = set(LeadAiOptOut.objects.filter(phone__in=list(found)).values_list("phone", flat=True))
        new = {phone: item for phone, item in found.items() if phone not in known}
        by_how = Counter(item[0] for item in new.values())
        self.stdout.write(f"scanned {scanned} inbound message(s); {len(found)} phone(s) asked us to stop; {len(known)} already in the registry")
        for how in ORDER:
            if by_how[how]:
                self.stdout.write(f"  {how.lower()}: {by_how[how]}")
        if dry_run:
            shown: dict = defaultdict(int)
            for phone, (how, reason, _) in new.items():
                if shown[how] >= EXAMPLES:
                    continue
                shown[how] += 1
                self.stdout.write(f"  e.g. +{phone[:5]}… {how.lower()}: {' '.join(str(reason or '').split())[:60]}")
            self.stdout.write(f"would add {len(new)} phone(s); nothing stored")
            return
        added = 0
        for phone, (how, reason, conversation_id) in new.items():
            # Every row this adds says it came from the back-fill (its source) and how they asked (its reason).
            text = f"{how}: {' '.join(str(reason or '').split())}"
            if optout.record(phone, reason=text, source=optout.Source.IMPORT, conversation=_Conversation(conversation_id)):
                added += 1
        self.stdout.write(f"added {added} phone(s)")


STATE_SOURCES = (
    LeadAiChatState.StopReason.STOP_ALL,
    LeadAiChatState.StopReason.WRONG_NUMBER,
    LeadAiChatState.StopReason.SPAM,
)


class _Conversation:
    """optout.record reads a conversation's pk only."""

    def __init__(self, pk):
        self.pk = pk
