from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("campaigns", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="campaign",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("queued", "Queued"),
                    ("running", "Running"),
                    ("retrying", "Retrying"),
                    ("done", "Done"),
                    ("failed", "Failed"),
                    ("cancelled", "Cancelled"),
                ],
                db_index=True,
                default="queued",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="campaignrecipient",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("sent", "Sent"),
                    ("failed", "Failed"),
                    ("exhausted", "Exhausted"),
                    ("skipped", "Skipped"),
                ],
                db_index=True,
                default="pending",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="campaignrecipient",
            name="attempt_count",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="campaignrecipient",
            name="last_attempt_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="campaignrecipient",
            name="next_retry_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
