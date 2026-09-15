import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="FeedbackReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("body", models.TextField()),
                (
                    "status",
                    models.CharField(
                        choices=[("open", "Open"), ("solved", "Solved")],
                        db_index=True,
                        default="open",
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("solved_at", models.DateTimeField(blank=True, null=True)),
                ("admin_note", models.TextField(blank=True)),
                (
                    "agent",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="feedback_reports",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "solved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="solved_feedback_reports",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="FeedbackAttachment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file", models.FileField(upload_to="feedback/%Y/%m/")),
                (
                    "kind",
                    models.CharField(choices=[("image", "Image"), ("video", "Video")], max_length=16),
                ),
                ("mime_type", models.CharField(blank=True, max_length=128)),
                ("file_name", models.CharField(blank=True, max_length=255)),
                ("size_bytes", models.PositiveBigIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "report",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attachments",
                        to="feedback.feedbackreport",
                    ),
                ),
            ],
            options={
                "ordering": ["id"],
            },
        ),
    ]
