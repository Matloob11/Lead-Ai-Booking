"""Queue shops chats the reply cap held back, now that the hour cap is 30. Nothing is sent from this process;
the Lead AI worker answers them.

Run: ops/wa.sh leadai-answer-capped
"""

from apps.leadai.assistant import caps
from apps.leadai.tasks import assistant_turn

print("shops_per_hour", caps.SHOPS_PER_HOUR, "shops_per_day", caps.SHOPS_PER_DAY)
ids = caps.to_answer()
print("queued_ids", ids)
for message_id in ids:
    assistant_turn.apply_async(args=[message_id], kwargs={"requeued": True})
print("QUEUED", len(ids))
