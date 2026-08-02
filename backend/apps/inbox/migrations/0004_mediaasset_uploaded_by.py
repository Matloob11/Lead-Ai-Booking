from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('inbox', '0003_conversation_last_message_kind'),
    ]

    operations = [
        migrations.AddField(
            model_name='mediaasset',
            name='uploaded_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='uploads',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
