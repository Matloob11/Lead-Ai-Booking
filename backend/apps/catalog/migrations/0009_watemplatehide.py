from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0009_fill_agent_community"),
        ("catalog", "0008_add_dubai10wbx_numbers"),
    ]

    operations = [
        migrations.CreateModel(
            name="WaTemplateHide",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("waba_business_id", models.CharField(db_index=True, max_length=64)),
                ("name", models.CharField(max_length=255)),
                ("hidden_at", models.DateTimeField(auto_now_add=True)),
                (
                    "hidden_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="accounts.agent",
                    ),
                ),
            ],
            options={
                "ordering": ["-hidden_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="watemplatehide",
            constraint=models.UniqueConstraint(
                fields=("waba_business_id", "name"),
                name="unique_hidden_template_per_waba",
            ),
        ),
    ]
