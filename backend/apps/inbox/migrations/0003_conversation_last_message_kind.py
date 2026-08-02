from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inbox', '0002_mediaasset_download_error_mediaasset_source_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='conversation',
            name='last_message_kind',
            field=models.CharField(blank=True, max_length=16),
        ),
    ]
