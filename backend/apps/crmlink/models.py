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

    message = models.OneToOneField(
        "inbox.Message", on_delete=models.CASCADE, related_name="crm_mirror"
    )
    entity_type = models.CharField(max_length=16)
    entity_id = models.PositiveIntegerField()
    comment_id = models.PositiveBigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["entity_type", "entity_id"])]

    def __str__(self):
        return f"message {self.message_id} -> {self.entity_type} {self.entity_id}"
