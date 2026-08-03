from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("accounts", "0003_accessrequest")]

    operations = [
        migrations.AddField(
            model_name="agent",
            name="display_name_is_custom",
            field=models.BooleanField(default=False),
        ),
    ]
