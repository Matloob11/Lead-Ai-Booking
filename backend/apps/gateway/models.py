from django.db import models


class WebhookEvent(models.Model):
    """Every callback alots.io makes, stored before anything is parsed.

    Kept raw and forever: it is the only record of what the gateway actually
    said, so a parsing bug can be fixed and the backlog replayed rather than
    lost. Processing happens out of band in a Celery task.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSED = "processed", "Processed"
        FAILED = "failed", "Failed"
        IGNORED = "ignored", "Ignored"

    payload = models.JSONField()
    phone_number_id = models.CharField(max_length=64, blank=True, db_index=True)

    # Meta redelivers callbacks that were not acknowledged in time, so the same
    # wamid can arrive twice. Set for message events, blank for the rest.
    dedupe_key = models.CharField(max_length=160, blank=True, db_index=True)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    error = models.TextField(blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)

    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.status} event #{self.pk}"


class PanelSession(models.Model):
    """The one signed-in alots *panel* session the server keeps alive.

    Seeded from ``ALOTS_UI_COOKIE_B64`` (a browser login — ``ops/wa.sh
    set-alots-ui-cookie``). alots' auth ticket lasts six hours and slides, so
    every answer that renews a cookie is folded back in here and a keepalive
    request every few minutes stops both the ticket and the server-side
    session from lapsing. One row; see ``apps/gateway/panel.py``.
    """

    cookie = models.TextField(blank=True)
    # sha256 of the env seed this row came from — a new seed replaces the row.
    seed_fingerprint = models.CharField(max_length=64, blank=True)
    # The auth cookie's own Expires, when alots last said.
    expires_at = models.DateTimeField(null=True, blank=True)
    last_ok_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"alots panel session (ok {self.last_ok_at:%Y-%m-%d %H:%M})" if self.last_ok_at else "alots panel session"


class ApiCall(models.Model):
    """Outbound calls to alots.io, for cost tracing and failure forensics."""

    method = models.CharField(max_length=8)
    path = models.CharField(max_length=255)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    request_body = models.JSONField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.method} {self.path} -> {self.status_code}"
