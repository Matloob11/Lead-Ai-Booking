from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('inbox', '0005_contact_notes'),
    ]

    operations = [
        migrations.CreateModel(
            name='Label',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=64, unique=True)),
                ('colour', models.CharField(default='#25D366', max_length=16)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering': ['name']},
        ),
        migrations.CreateModel(
            name='QuickReply',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('shortcut', models.CharField(help_text='Typed after / to insert it', max_length=32)),
                ('body', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('owner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='quick_replies', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['shortcut']},
        ),
        migrations.AddConstraint(
            model_name='quickreply',
            constraint=models.UniqueConstraint(fields=('owner', 'shortcut'), name='unique_shortcut_per_owner'),
        ),
        migrations.AddField(
            model_name='conversation',
            name='is_pinned',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='conversation',
            name='is_archived',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='conversation',
            name='labels',
            field=models.ManyToManyField(blank=True, related_name='conversations', to='inbox.label'),
        ),
        migrations.AddField(
            model_name='message',
            name='reply_to',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='replies', to='inbox.message'),
        ),
        migrations.AlterModelOptions(
            name='conversation',
            options={'ordering': ['-is_pinned', '-last_message_at', '-created_at']},
        ),
    ]
