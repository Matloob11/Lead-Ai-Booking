"""Agent reports for the Official API panel.

A separate app so Conversation / Message / accounts stay untouched — those are
mid-edit in other sessions. Agents write the issue; admins mark it solved.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class FeedbackReport(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        SOLVED = "solved", "Solved"

    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="feedback_reports",
    )
    body = models.TextField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    solved_at = models.DateTimeField(null=True, blank=True)
    solved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="solved_feedback_reports",
    )
    admin_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"#{self.pk} {self.agent} ({self.status})"

    def solve(self, by, note=""):
        self.status = self.Status.SOLVED
        self.solved_at = timezone.now()
        self.solved_by = by
        self.admin_note = (note or "")[:2000]
        self.save(update_fields=["status", "solved_at", "solved_by", "admin_note"])
        return self


class FeedbackAttachment(models.Model):
    class Kind(models.TextChoices):
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"

    report = models.ForeignKey(
        FeedbackReport, on_delete=models.CASCADE, related_name="attachments"
    )
    file = models.FileField(upload_to="feedback/%Y/%m/")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    mime_type = models.CharField(max_length=128, blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.file_name or f"attachment #{self.pk}"
