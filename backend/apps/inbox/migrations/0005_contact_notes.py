from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inbox', '0004_mediaasset_uploaded_by'),
    ]

    operations = [
        migrations.AddField(
            model_name='contact',
            name='notes',
            field=models.TextField(blank=True),
        ),
    ]
