from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inbox', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='mediaasset',
            name='download_error',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='mediaasset',
            name='source_url',
            field=models.TextField(blank=True),
        ),
    ]
