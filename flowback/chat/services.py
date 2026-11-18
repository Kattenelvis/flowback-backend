"""Everything that changes chat state goes through this module.

A chat (MessageChannel) has a kind, and the kind's ChannelPolicy decides what its members may do.
A user's membership (MessageChannelParticipant) moves between these statuses:

    invited  --accept-->  active  --leave/removed-->  left
       |                    ^                           |
       +--decline--> declined     <---rejoin/invite-----+

Only active members can read and send messages. Each change is pushed to connected websockets
after the transaction commits (see realtime.py).
"""
from django.db import transaction, IntegrityError
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from flowback.chat import realtime
from flowback.chat.models import (MessageChannel, Message, MessageChannelParticipant, MessageFileCollection,
                                  MessageChannelTopic)
from flowback.chat.selectors import get_membership, channel_summary
from flowback.chat.serializers import MessageSerializer, ChannelSerializer
from flowback.common.services import get_object, model_update
from flowback.files.services import upload_collection
from flowback.notification.models import NotificationChannel
from flowback.user.models import User

Kind = MessageChannel.Kind
Status = MessageChannelParticipant.Status

MAX_INVITES = 25


# Events sent to websockets

def _message_event(event_type: str, message: Message, client_id: str = None) -> dict:
    event = dict(type=event_type, channel_id=message.channel_id, message=MessageSerializer(message).data)
    if client_id:
        event['client_id'] = client_id

    return event


def _publish_channel_added(user: User, channel: MessageChannel) -> None:
    def build():
        summary = _summary_data(user=user, channel_id=channel.id)
        return dict(type='channel.added', channel=summary) if summary else None

    realtime.publish_to_user(user.id, build)


def _publish_channel_updated(channel: MessageChannel) -> None:
    def build():
        try:
            channel.refresh_from_db()
        except MessageChannel.DoesNotExist:  # Deleted in the same transaction
            return None

        return dict(type='channel.updated',
                    channel_id=channel.id,
                    # Direct messages are titled after the other person, which differs per member
                    title=None if channel.kind == Kind.USER else channel.title,
                    member_count=channel.messagechannelparticipant_set.filter(status=Status.ACTIVE).count())

    realtime.publish_to_channel(channel.id, build)


def _publish_channel_removed(user_id: int, channel_id: int) -> None:
    realtime.unsubscribe(user_id, channel_id)
    realtime.publish_to_user(user_id, dict(type='channel.removed', channel_id=channel_id))


def _summary_data(*, user: User, channel_id: int) -> dict | None:
    try:
        return ChannelSerializer(channel_summary(user=user, channel_id=channel_id)).data
    except ValidationError:  # No longer a member by the time the transaction committed
        return None


def _announce(*, channel: MessageChannel, user: User, event: str, text: str) -> Message:
    """Writes an info message such as "User X joined the channel" and sends it to the members."""
    message = Message.objects.create(user=user, channel=channel, type=Message.Type.INFO, event=event, message=text)
    realtime.publish_to_channel(channel.id, lambda: _message_event('message.created', message))

    return message


# Membership changes shared by every kind of chat

def _join(*, channel: MessageChannel, user: User) -> MessageChannelParticipant:
    """Makes the user an active member, creating the membership if needed."""
    participant, created = MessageChannelParticipant.objects.get_or_create(
        channel=channel, user=user, defaults=dict(status=Status.ACTIVE, last_read_at=timezone.now()))

    if not created:
        if participant.is_active:
            return participant

        participant.status = Status.ACTIVE
        participant.last_read_at = timezone.now()  # Earlier history doesn't count as unread
        participant.save(update_fields=['status', 'last_read_at', 'updated_at'])

    realtime.subscribe(user.id, channel.id)
    _publish_channel_added(user, channel)
    _announce(channel=channel, user=user, event=Message.Event.JOINED, text=f"User {user.username} joined the channel")
    _publish_channel_updated(channel)

    return participant


def _invite(*, channel: MessageChannel, user: User, invited_by: User) -> MessageChannelParticipant:
    """Invites the user unless they're already a member or invited."""
    participant = MessageChannelParticipant.objects.filter(channel=channel, user=user).first()

    if participant and participant.status in [Status.ACTIVE, Status.INVITED]:
        return participant

    if participant:
        participant.status = Status.INVITED
        participant.invited_by = invited_by
        participant.save(update_fields=['status', 'invited_by', 'updated_at'])

    else:
        participant = MessageChannelParticipant.objects.create(channel=channel, user=user, status=Status.INVITED,
                                                               invited_by=invited_by)

    title = channel.title or invited_by.username
    user.notify_chat(action=NotificationChannel.Action.CREATED,
                     message=f"{invited_by.username} invited you to the chat {title}",
                     message_channel_id=channel.id,
                     message_channel_title=title)
    _publish_channel_added(user, channel)

    return participant


def _leave(*, participant: MessageChannelParticipant) -> None:
    """Ends an active membership or an invite."""
    was_active = participant.is_active
    participant.status = Status.LEFT if was_active else Status.DECLINED
    participant.save(update_fields=['status', 'updated_at'])

    _publish_channel_removed(participant.user_id, participant.channel_id)

    if was_active:
        _announce(channel=participant.channel,
                  user=participant.user,
                  event=Message.Event.LEFT,
                  text=f"User {participant.user.username} left the channel")
        _publish_channel_updated(participant.channel)


# Chats owned by groups and work groups

def channel_create(*, kind: str, title: str = None) -> MessageChannel:
    channel = MessageChannel(kind=kind, title=title)
    channel.full_clean()
    channel.save()

    return channel


def channel_close(*, channel: MessageChannel) -> None:
    """Removes everyone from a chat at once, without announcing each departure.

    Called before a group or work group is deleted, so that the removal of each of its members doesn't post
    a "left" message to a chat that's about to be deleted.
    """
    members = channel.messagechannelparticipant_set.filter(status__in=[Status.ACTIVE, Status.INVITED])
    for user_id in members.values_list('user_id', flat=True):
        _publish_channel_removed(user_id, channel.id)

    members.update(status=Status.LEFT)


def channel_delete(*, channel: MessageChannel) -> None:
    """Deletes a chat and removes it from its members' chat lists."""
    channel_close(channel=channel)
    channel.delete()


def channel_set_title(*, channel: MessageChannel, title: str) -> None:
    """Renames a chat on behalf of whatever owns it, e.g. when a group is renamed."""
    channel.title = title
    channel.save(update_fields=['title', 'updated_at'])
    _publish_channel_updated(channel)


def channel_member_add(*, channel: MessageChannel, user: User) -> MessageChannelParticipant:
    """Adds a member to a chat whose membership is managed by its group or work group."""
    return _join(channel=channel, user=user)


def channel_member_remove(*, channel: MessageChannel, user: User) -> None:
    """Removes a member from a chat whose membership is managed by its group or work group."""
    participant = MessageChannelParticipant.objects.filter(channel=channel, user=user, status=Status.ACTIVE).first()
    if participant:
        _leave(participant=participant)


# Direct messages and group chats

def _can_message_directly(*, user: User, target: User) -> bool:
    """Whether the user can start a direct message with the target without the target accepting an invite."""
    from flowback.group.models import GroupUser

    if user.is_superuser or target.chat_status == User.PublicStatus.PUBLIC:
        return True

    if target.chat_status == User.PublicStatus.GROUP_ONLY:
        shared_groups = GroupUser.objects.filter(user=user, active=True).values('group_id')
        return GroupUser.objects.filter(user=target, active=True, group_id__in=shared_groups).exists()

    return False


def direct_channel_get_or_create(*, user: User, target_user_id: int) -> MessageChannel:
    """Opens the direct message between two users, creating it if needed.

    Opening a direct message you've been invited to accepts the invite. The other person joins straight
    away if their chat settings allow it, otherwise they're invited.
    """
    if target_user_id == user.id:
        raise ValidationError("You cannot start a chat with yourself")

    target = get_object(User, id=target_user_id, is_active=True, error_message="User does not exist")
    dm_key = MessageChannel.make_dm_key(user.id, target.id)

    with transaction.atomic():
        channel = MessageChannel.objects.select_for_update().filter(dm_key=dm_key).first()

        if channel is None:
            try:
                with transaction.atomic():
                    channel = MessageChannel.objects.create(kind=Kind.USER, dm_key=dm_key)
            except IntegrityError:  # Someone else created it at the same moment
                channel = MessageChannel.objects.select_for_update().get(dm_key=dm_key)

        _join(channel=channel, user=user)

        other = MessageChannelParticipant.objects.filter(channel=channel, user=target).first()
        if other is None or other.status == Status.LEFT:
            if _can_message_directly(user=user, target=target):
                _join(channel=channel, user=target)
            else:
                _invite(channel=channel, user=target, invited_by=user)

    return channel


def group_chat_create(*, user: User, title: str = None, user_ids: list[int]) -> MessageChannel:
    """Creates a group chat with the user in it and invites everyone else."""
    user_ids = set(user_ids) - {user.id}

    if not user_ids:
        raise ValidationError("Add at least one other person to the group chat")

    if len(user_ids) > MAX_INVITES:
        raise ValidationError(f"Cannot invite more than {MAX_INVITES} users at once")

    targets = list(User.objects.filter(id__in=user_ids, is_active=True).order_by('username'))
    if len(targets) != len(user_ids):
        raise ValidationError("Some of the selected users do not exist")

    title = (title or '').strip() or _generate_title([user, *targets])

    with transaction.atomic():
        channel = channel_create(kind=Kind.USER_GROUP, title=title)
        _join(channel=channel, user=user)

        for target in targets:
            _invite(channel=channel, user=target, invited_by=user)

    return channel


def _generate_title(users: list[User]) -> str:
    title = ''
    for i, user in enumerate(users):
        if len(title + user.username) > 50:
            return f"{title} and {len(users) - i} other(s)"

        title += f", {user.username}" if title else user.username

    return title


def _lock_channel(channel_id: int) -> None:
    """Makes concurrent membership changes to one chat wait for each other. Call inside a transaction."""
    MessageChannel.objects.select_for_update().filter(id=channel_id).first()


def channel_invite(*, user: User, channel_id: int, user_ids: list[int]) -> None:
    participant = get_membership(user_id=user.id, channel_id=channel_id)
    channel = participant.channel

    if not channel.policy.can_invite:
        raise ValidationError("You cannot invite people to this chat")

    if len(user_ids) > MAX_INVITES:
        raise ValidationError(f"Cannot invite more than {MAX_INVITES} users at once")

    targets = list(User.objects.filter(id__in=set(user_ids), is_active=True).exclude(id=user.id))
    if len(targets) != len(set(user_ids) - {user.id}):
        raise ValidationError("Some of the selected users do not exist")

    with transaction.atomic():
        _lock_channel(channel_id)
        get_membership(user_id=user.id, channel_id=channel_id)  # Still a member once we have the lock

        for target in targets:
            _invite(channel=channel, user=target, invited_by=user)


def channel_invite_accept(*, user: User, channel_id: int) -> MessageChannelParticipant:
    with transaction.atomic():
        _lock_channel(channel_id)
        participant = get_membership(user_id=user.id, channel_id=channel_id, statuses=[Status.INVITED])
        return _join(channel=participant.channel, user=user)


def channel_invite_decline(*, user: User, channel_id: int) -> None:
    with transaction.atomic():
        _lock_channel(channel_id)
        participant = get_membership(user_id=user.id, channel_id=channel_id, statuses=[Status.INVITED])
        _leave(participant=participant)


def channel_leave(*, user: User, channel_id: int) -> None:
    """Leaves a chat. The chat is deleted once nobody is left in it."""
    with transaction.atomic():
        _lock_channel(channel_id)
        participant = get_membership(user_id=user.id, channel_id=channel_id)
        channel = participant.channel

        if not channel.policy.can_leave:
            raise ValidationError("You cannot leave this chat")

        _leave(participant=participant)

        if not channel.messagechannelparticipant_set.filter(status=Status.ACTIVE).exists():
            channel_delete(channel=channel)


def channel_rename(*, user: User, channel_id: int, title: str) -> MessageChannel:
    participant = get_membership(user_id=user.id, channel_id=channel_id)
    channel = participant.channel

    if not channel.policy.can_rename:
        raise ValidationError("You cannot rename this chat")

    title = title.strip()
    if not title:
        raise ValidationError("Title cannot be empty")

    with transaction.atomic():
        channel.title = title
        channel.full_clean()
        channel.save(update_fields=['title', 'updated_at'])

        _announce(channel=channel, user=user, event=Message.Event.RENAMED,
                  text=f"User {user.username} renamed the chat to {title}")
        _publish_channel_updated(channel)

    return channel


def channel_mark_read(*, user: User, channel_id: int) -> None:
    participant = get_membership(user_id=user.id, channel_id=channel_id)
    participant.last_read_at = timezone.now()
    participant.save(update_fields=['last_read_at', 'updated_at'])

    # Clears the unread marker in the user's other tabs too
    realtime.publish_to_user(user.id, dict(type='channel.read', channel_id=channel_id))


# Messages

def message_create(*,
                   user_id: int,
                   channel_id: int,
                   message: str,
                   attachments_id: int = None,
                   parent_id: int = None,
                   topic_id: int = None,
                   client_id: str = None) -> Message:
    """Sends a message. client_id is echoed back to the sender so it can match the message to its draft."""
    participant = get_membership(user_id=user_id, channel_id=channel_id)

    if topic_id is not None and not MessageChannelTopic.objects.filter(id=topic_id, channel_id=channel_id).exists():
        raise ValidationError("Topic does not exist")

    if parent_id is not None and not Message.objects.filter(id=parent_id, channel_id=channel_id,
                                                            topic_id=topic_id, active=True).exists():
        raise ValidationError("Parent does not exist")

    if attachments_id is not None and not MessageFileCollection.objects.filter(id=attachments_id, user_id=user_id,
                                                                               channel_id=channel_id).exists():
        raise ValidationError("Unauthorized usage of Attachments")

    message = Message(user_id=user_id,
                      channel_id=channel_id,
                      message=message,
                      attachments_id=attachments_id,
                      parent_id=parent_id,
                      topic_id=topic_id)
    message.full_clean()
    message.save()

    # Sending a message means you've read the chat
    participant.last_read_at = message.created_at
    participant.save(update_fields=['last_read_at', 'updated_at'])

    realtime.publish_to_channel(channel_id, lambda: _message_event('message.created', message, client_id))

    return message


def _get_own_message(*, user_id: int, message_id: int) -> Message:
    message = get_object(Message, id=message_id, active=True)

    if message.user_id != user_id or message.type != Message.Type.MESSAGE:
        raise ValidationError('User is not author of message')

    get_membership(user_id=user_id, channel_id=message.channel_id)

    return message


def message_update(*, user_id: int, message_id: int, **data) -> Message:
    message = _get_own_message(user_id=user_id, message_id=message_id)
    # updated_at is listed so auto_now bumps it, update_fields skips it otherwise
    message, has_updated = model_update(instance=message, fields=['message', 'updated_at'], data=data)

    realtime.publish_to_channel(message.channel_id, lambda: _message_event('message.updated', message))

    return message


def message_delete(*, user_id: int, message_id: int) -> Message:
    message = _get_own_message(user_id=user_id, message_id=message_id)
    message.active = False
    message.save(update_fields=['active', 'updated_at'])

    realtime.publish_to_channel(message.channel_id, dict(type='message.deleted',
                                                         channel_id=message.channel_id,
                                                         message_id=message.id))

    return message


def message_files_upload(*, user_id: int, channel_id: int, files: list) -> MessageFileCollection:
    participant = get_membership(user_id=user_id, channel_id=channel_id)
    upload_to = f"{MessageFileCollection.ATTACHMENTS_UPLOAD_TO}/{participant.channel.kind}"

    file_collection = upload_collection(user_id=user_id, file=files,
                                        upload_to=upload_to)

    message_collection = MessageFileCollection(user_id=user_id, channel_id=channel_id, file_collection=file_collection)
    message_collection.full_clean()
    message_collection.save()

    return message_collection


def message_channel_topic_create(*, channel_id: int, topic_name: str, hidden: bool = False):
    channel = get_object(MessageChannel, id=channel_id)
    topic = MessageChannelTopic(channel=channel, name=topic_name, hidden=hidden)
    topic.full_clean()
    topic.save()

    return topic


def message_channel_topic_delete(*, channel_id: int, topic_id: int):
    topic = get_object(MessageChannelTopic, channel_id=channel_id, id=topic_id)
    topic.delete()
