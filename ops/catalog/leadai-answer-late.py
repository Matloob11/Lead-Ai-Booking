# One-off (2026-10-19): answer the campaign replies the Lead AI dropped as too old.
#
# Right after the intl_city_property_reconnect send (campaigns 549-553), replies came
# in faster than worker-leadai could take them; messages waited over 15 minutes and
# engine.run_turn skipped them as stale (243 "stale" alerts), so 92 customers got no
# answer. This runs the normal engine turn on each one, with STALE_AFTER lifted for
# this process only.
#
# A chat is taken only when its customer's last message (since the send) has no turn,
# nothing went out after it (no agent or bot reply since), and the chat is neither
# stopped nor paused; run_turn checks the rest (opt-outs, handovers) as on any turn.
#
# LATE_MODE=list prints what it would answer and sends nothing (the default);
# LATE_MODE=send answers them. LATE_LIMIT caps how many this run takes.
#
# Run in the web container through `ops/wa.sh leadai-answer-late [list|send] [limit]`.

import datetime as dt
import os
import time

from django.utils import timezone

from apps.inbox.models import Message
from apps.leadai.assistant import engine
from apps.leadai.models import LeadAiChat, LeadAiChatState, LeadAiTurn

MODE = os.environ.get("LATE_MODE", "list")
LIMIT = int(os.environ.get("LATE_LIMIT", "100"))
CAMPAIGNS = (549, 550, 551, 552, 553)
SINCE = dt.datetime(2026, 10, 19, 8, 0, tzinfo=dt.timezone.utc)

targets = []
chats = LeadAiChat.objects.filter(campaign_id__in=CAMPAIGNS, active=True).select_related("conversation").order_by("pk")
for chat in chats:
    conversation = chat.conversation
    # The newest answerable message as the engine reads it (_newer_inbound goes by pk, not created_at: a burst stored out
    # of time order otherwise sends every run to "a newer message will be answered").
    last_in = (
        engine._answerable(Message.objects.filter(conversation=conversation, direction=Message.Direction.INBOUND, created_at__gt=SINCE))
        .order_by("-pk")
        .first()
    )
    if last_in is None or LeadAiTurn.objects.filter(inbound=last_in).exists():
        continue
    if timezone.now() - last_in.created_at < engine.STALE_AFTER:
        continue  # a fresh message is the normal queue's to answer
    replied_since = (
        Message.objects.filter(conversation=conversation, direction=Message.Direction.OUTBOUND, created_at__gt=last_in.created_at)
        .exclude(kind="system")
        .exists()
    )
    if replied_since:
        continue
    state = LeadAiChatState.objects.filter(conversation=conversation).first()
    if state is not None and (state.stopped_at or state.paused_at):
        continue
    targets.append((conversation.pk, last_in.pk, last_in.kind, last_in.created_at))

print(f"mode {MODE} | waiting chats: {len(targets)} | this run takes: {min(len(targets), LIMIT)}")
for conversation_pk, message_pk, kind, at in targets[:LIMIT]:
    print(f"  conv {conversation_pk} message {message_pk} {kind} at {timezone.localtime(at):%H:%M}")

if MODE == "send":
    engine.STALE_AFTER = dt.timedelta(hours=20)  # this process only: the customer still waits for an answer
    counts = {}
    errors = 0
    for conversation_pk, message_pk, _, _ in targets[:LIMIT]:
        try:
            outcome = engine.run_turn(message_pk)
            counts[outcome.status] = counts.get(outcome.status, 0) + 1
            print(f"  conv {conversation_pk}: {outcome.status} {outcome.reason}")
        except engine.NotReady as exc:
            # A voice note still downloading after hours will not come: the engine's last attempt gives up on it, and
            # an unheard voice note goes to a person as on any turn.
            try:
                outcome = engine.run_turn(message_pk, attempt=len(engine.AUDIO_WAITS))
                counts[outcome.status] = counts.get(outcome.status, 0) + 1
                print(f"  conv {conversation_pk}: {outcome.status} {outcome.reason} (after: {exc})")
            except engine.NotReady as again:
                counts["not ready"] = counts.get("not ready", 0) + 1
                print(f"  conv {conversation_pk}: not ready ({again})")
        except Exception as exc:  # noqa: BLE001 - reported, and five in a row stop the run
            errors += 1
            print(f"  conv {conversation_pk}: ERROR {type(exc).__name__}: {str(exc)[:200]}")
            if errors >= 5:
                print("stopping after 5 errors")
                break
        time.sleep(2)
    print(f"done: {counts} | errors {errors}")
