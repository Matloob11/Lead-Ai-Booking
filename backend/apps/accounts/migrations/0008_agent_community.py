from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_agent_product_access"),
    ]

    operations = [
        migrations.AddField(
            model_name="agent",
            name="community",
            field=models.CharField(blank=True, max_length=120),
        ),
    ]
