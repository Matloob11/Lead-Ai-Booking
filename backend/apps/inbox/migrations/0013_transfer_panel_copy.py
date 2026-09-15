from django.db import migrations, models
import django.db.models.deletion


def seed_transferred_label(apps, schema_editor):
    Label = apps.get_model("inbox", "Label")
    Label.objects.get_or_create(name="Transferred", defaults={"colour": "#c9a227"})


def unseed_transferred_label(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("inbox", "0012_message_kind_album_pinned"),
    ]

    operations = [
        migrations.AddField(
            model_name="conversation",
            name="linked_conversation",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="inbox.conversation",
            ),
        ),
        migrations.AddField(
            model_name="message",
            name="mirrored_from",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="panel_copies",
                to="inbox.message",
            ),
        ),
        migrations.AddConstraint(
            model_name="message",
            constraint=models.UniqueConstraint(
                condition=models.Q(("mirrored_from__isnull", False)),
                fields=("conversation", "mirrored_from"),
                name="unique_panel_copy_per_peer",
            ),
        ),
        migrations.RunPython(seed_transferred_label, unseed_transferred_label),
    ]
