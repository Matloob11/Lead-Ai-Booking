# Read-only probe (2026-10-24, Lead AI round 27; ops/wa.sh probe-leadai-resume), through the running web image:
# on the live chats the assistant stopped, what the round-27 rule (engine.resume_reason) says about the customer's
# messages after the stop: which chats take themselves up again on the customer's next message, and why the others stay
# stopped. And whether "Yes I have ma shops" with the model's other_need tag reads as the shop track (tracks.decide).
# Conversation ids only, no phone numbers; nothing is written; no message is sent.
from apps.inbox.models import Message
from apps.leadai import ic_templates
from apps.leadai.assistant import engine, tracks
from apps.leadai.models import LeadAiChatState

problems = []
if not hasattr(engine, "resume_reason"):
    problems.append("the running image has no engine.resume_reason: round 27 is not live")
else:
    stopped = LeadAiChatState.objects.filter(stopped_at__isnull=False, conversation__lead_ai_chat__active=True).select_related(
        "conversation__contact"
    )
    counts = {}
    lifting = []
    for state in stopped.order_by("conversation_id"):
        after = list(
            Message.objects.filter(conversation=state.conversation, direction=Message.Direction.INBOUND, created_at__gt=state.stopped_at)
            .exclude(kind__in=("reaction", "system"))
            .order_by("pk")
        )
        why = engine.resume_reason(state.conversation, state, after) if after else ""
        key = f"{state.stop_reason or '-'}: {'customer wrote after' if after else 'nothing after'}, {'lifts' if why else 'stays'}"
        counts[key] = counts.get(key, 0) + 1
        if why:
            lifting.append(f"  chat {state.conversation_id} ({state.stop_reason}): {why}; last after the stop: {after[-1].kind}")
    print(f"stopped Lead AI chats: {sum(counts.values())}")
    for key in sorted(counts):
        print(f"  {key}: {counts[key]}")
    print("would take themselves up again on the customer's next message:" if lifting else "none would lift on what is already there")
    for line in lifting:
        print(line)

decision = tracks.decide(
    words=["Yes I have ma shops"], facts={"property_type": "shop", "intent": "rent"}, lead={}, stored="",
    template_kind=ic_templates.MIXED, model_tag="other_need",
)
print(f'"Yes I have ma shops" with other_need: track {decision.track}')
if decision.track != tracks.SHOP:
    problems.append(f"the shop words guard is not live (track {decision.track})")

if problems:
    print("PROBE_FAILED")
    for problem in problems:
        print(" -", problem)
else:
    print("passed | round 27: the resume rule reads the live stopped chats, and shop words stay on the shop track")
