from django.db import migrations


class Migration(migrations.Migration):
    """Chat invites are now memberships with the status 'invited' (see chat.0012_chat_rewrite_data)."""

    dependencies = [
        ('user', '0030_alter_user_username'),
        ('chat', '0012_chat_rewrite_data'),
    ]

    operations = [
        migrations.DeleteModel(
            name='UserChatInvite',
        ),
    ]
