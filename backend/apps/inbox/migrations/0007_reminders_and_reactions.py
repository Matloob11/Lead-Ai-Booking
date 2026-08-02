from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('inbox', '0006_quick_replies_labels_and_replies'),
    ]

    operations = [
        migrations.AddField(
            model_name='message',
            name='reactions',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.CreateModel(
            name='Reminder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('due_at', models.DateTimeField(db_index=True)),
                ('note', models.CharField(blank=True, max_length=255)),
                ('is_done', models.BooleanField(default=False)),
                ('fired_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('agent', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reminders', to=settings.AUTH_USER_MODEL)),
                ('conversation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reminders', to='inbox.conversation')),
            ],
            options={'ordering': ['due_at']},
        ),
        migrations.AddIndex(
            model_name='reminder',
            index=models.Index(fields=['agent', 'is_done', 'due_at'], name='inbox_remin_agent_i_487ead_idx'),
        ),
    ]
