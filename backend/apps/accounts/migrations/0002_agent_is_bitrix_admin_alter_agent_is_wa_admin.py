
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='agent',
            name='is_bitrix_admin',
            field=models.BooleanField(default=False, help_text='Mirrored from the portal at sign-in'),
        ),
        migrations.AlterField(
            model_name='agent',
            name='is_wa_admin',
            field=models.BooleanField(default=False, help_text='Granted here, independent of Bitrix'),
        ),
    ]
