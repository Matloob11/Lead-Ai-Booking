from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("inbox", "0011_shared_asset_and_default_labels"),
    ]

    operations = [
        migrations.AlterField(
            model_name="message",
            name="kind",
            field=models.CharField(
                choices=[
                    ("text", "Text"),
                    ("template", "Template"),
                    ("image", "Image"),
                    ("document", "Document"),
                    ("audio", "Audio"),
                    ("video", "Video"),
                    ("sticker", "Sticker"),
                    ("location", "Location"),
                    ("contacts", "Contacts"),
                    ("interactive", "Interactive"),
                    ("button", "Button reply"),
                    ("reaction", "Reaction"),
                    ("album", "Album"),
                    ("pinned_message", "Pinned message"),
                    ("system", "System"),
                    ("unknown", "Unknown"),
                ],
                default="text",
                max_length=16,
            ),
        ),
    ]
