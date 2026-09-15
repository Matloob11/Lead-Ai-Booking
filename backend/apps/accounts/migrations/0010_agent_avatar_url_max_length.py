from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0009_fill_agent_community"),
    ]

    operations = [
        migrations.AlterField(
            model_name="agent",
            name="avatar_url",
            field=models.URLField(blank=True, max_length=1000),
        ),
    ]
