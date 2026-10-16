"""Moves chat data onto the membership statuses and direct message keys added in 0011.

Before this, a membership was an `active` flag plus, for invites, a separate user.UserChatInvite row
whose `rejected` field was None (pending), True (declined) or False (accepted). The frontend also
"left" group chats by pushing `closed_at` far into the future.
"""
from datetime import datetime, timezone

from django.db import migrations
from django.db.models import Exists, OuterRef, F, Max
from django.db.models.functions import Coalesce, Now

FAR_FUTURE = datetime(2900, 1, 1, tzinfo=timezone.utc)

INFO_EVENTS = [
    ('joined', dict(message__endswith='joined the channel')),
    ('left', dict(message__endswith='left the channel')),
    ('renamed', dict(message__startswith='Channel changed name to')),
]


def forwards(apps, schema_editor):
    MessageChannel = apps.get_model('chat', 'MessageChannel')
    Participant = apps.get_model('chat', 'MessageChannelParticipant')
    Message = apps.get_model('chat', 'Message')
    UserChatInvite = apps.get_model('user', 'UserChatInvite')

    def invites(**filters):
        return Exists(UserChatInvite.objects.filter(user_id=OuterRef('user_id'),
                                                    message_channel_id=OuterRef('channel_id'),
                                                    **filters))

    # Memberships
    Participant.objects.filter(active=True).update(status='active')
    Participant.objects.filter(active=False).update(status='left')
    Participant.objects.filter(active=False).filter(invites(rejected__isnull=True)).update(status='invited')
    Participant.objects.filter(active=False).filter(invites(rejected=True)).update(status='declined')
    Participant.objects.filter(channel__kind='user_group', closed_at__gte=FAR_FUTURE).update(status='left')

    # Read state. `timestamp` was bumped on every save, which is as close as the old data gets.
    Participant.objects.update(last_read_at=F('timestamp'))

    # One key per pair of users with a direct message. If a pair somehow has several, the most recently
    # used one gets the key and the others stay as they are.
    channels = (MessageChannel.objects
                .filter(kind='user')
                .annotate(last_message_id=Coalesce(Max('message__id'), 0))
                .order_by('-last_message_id', '-id'))
    taken = set()
    for channel in channels:
        user_ids = sorted(set(Participant.objects.filter(channel=channel).values_list('user_id', flat=True)))
        if len(user_ids) != 2:
            continue

        key = f"{user_ids[0]}:{user_ids[1]}"
        if key in taken:
            continue

        taken.add(key)
        MessageChannel.objects.filter(id=channel.id).update(dm_key=key)

    # Direct messages are now titled after the other person; the old "alice, bob" titles would go stale
    MessageChannel.objects.filter(kind='user').update(title=None)

    # Info messages
    for event, filters in INFO_EVENTS:
        Message.objects.filter(type='info', event__isnull=True, **filters).update(event=event)


def backwards(apps, schema_editor):
    Participant = apps.get_model('chat', 'MessageChannelParticipant')
    UserChatInvite = apps.get_model('user', 'UserChatInvite')

    Participant.objects.update(active=False, timestamp=Coalesce(F('last_read_at'), Now()))
    Participant.objects.filter(status='active').update(active=True)

    for participant in Participant.objects.filter(status__in=['invited', 'declined'],
                                                  channel__kind__in=['user', 'user_group']):
        UserChatInvite.objects.get_or_create(user_id=participant.user_id,
                                             message_channel_id=participant.channel_id,
                                             defaults=dict(rejected=None if participant.status == 'invited' else True))


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0011_chat_rewrite_schema'),
        ('user', '0030_alter_user_username'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
