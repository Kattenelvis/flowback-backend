from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('chat', '0010_alter_message_message_alter_message_type_and_more'),
        # Older group migrations create chats with the old `origin_name` field, so they must run first
        ('group', '0062_alter_group_blockchain_id'),
    ]

    operations = [
        migrations.RenameField(
            model_name='messagechannel',
            old_name='origin_name',
            new_name='kind',
        ),
        migrations.AlterField(
            model_name='messagechannel',
            name='kind',
            field=models.CharField(choices=[('user', 'Direct message'), ('user_group', 'Group chat'),
                                            ('group', 'Group'), ('workgroup', 'Work group')], max_length=255),
        ),
        migrations.AddField(
            model_name='messagechannel',
            name='dm_key',
            field=models.CharField(blank=True, max_length=64, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='messagechannelparticipant',
            name='status',
            field=models.CharField(choices=[('invited', 'Invited'), ('active', 'Active'), ('declined', 'Declined'),
                                            ('left', 'Left')], db_index=True, default='active', max_length=16),
        ),
        migrations.AddField(
            model_name='messagechannelparticipant',
            name='invited_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='messagechannelparticipant',
            name='last_read_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='message',
            name='type',
            field=models.CharField(choices=[('message', 'Message'), ('info', 'Info')], default='message',
                                   max_length=255),
        ),
        migrations.AddField(
            model_name='message',
            name='event',
            field=models.CharField(blank=True, choices=[('joined', 'Joined'), ('left', 'Left'),
                                                        ('renamed', 'Renamed')], max_length=32, null=True),
        ),
        migrations.AddIndex(
            model_name='message',
            index=models.Index(fields=['channel', '-id'], name='chat_message_channel_id_idx'),
        ),
    ]
