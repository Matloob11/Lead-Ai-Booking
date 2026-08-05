from django.db import models


class Mirror(models.Model):
    """A message that has already been copied into the CRM timeline.

    Without this there is nothing to stop the same message being posted twice.
    Celery runs with acks_late, so a worker that dies after the comment is
    created but before the task is acknowledged will run the whole task again —
    and the backfill below would repost the entire history every time somebody
    ran it. Bitrix has no idea a comment is a duplicate; it is happy to hold a
    hundred copies of the same line.

    Keyed on the message rather than on the comment, because the question being
    asked is always "has this one gone across yet".
    """

    # Many, not one. The same number can sit on a lead *and* on an Owner Data
    # record — an agent often works the owner side of a property from there and
    # never opens the lead — so one message can legitimately belong in two
    # timelines. It was a OneToOne until that turned up.
    message = models.ForeignKey(
        "inbox.Message", on_delete=models.CASCADE, related_name="crm_mirrors"
    )
    # "lead", "contact", or "DYNAMIC_1042" for a smart-process item.
    entity_type = models.CharField(max_length=32)
    entity_id = models.PositiveIntegerField()
    comment_id = models.PositiveBigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["message", "entity_type", "entity_id"],
                name="unique_mirror_per_record",
            )
        ]
        indexes = [models.Index(fields=["entity_type", "entity_id"])]

    def __str__(self):
        return f"message {self.message_id} -> {self.entity_type} {self.entity_id}"
