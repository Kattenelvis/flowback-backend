from dataclasses import dataclass

from django.db import models

from flowback.common.models import BaseModel
from flowback.common.validators import FieldNotBlankValidator
from flowback.files.models import FileCollection


@dataclass(frozen=True)
class ChannelPolicy:
    """What the members of a kind of chat are allowed to do."""
    # Membership follows the group or work group that owns the chat, so members can't join, leave or invite
    # through the chat itself
    managed: bool
    can_leave: bool
    can_rename: bool
    can_invite: bool


class MessageChannel(BaseModel):
    class Kind(models.TextChoices):
        USER = 'user', 'Direct message'
        USER_GROUP = 'user_group', 'Group chat'
        GROUP = 'group', 'Group'
        WORKGROUP = 'workgroup', 'Work group'

    POLICIES = {
        Kind.USER: ChannelPolicy(managed=False, can_leave=False, can_rename=False, can_invite=False),
        Kind.USER_GROUP: ChannelPolicy(managed=False, can_leave=True, can_rename=True, can_invite=True),
        Kind.GROUP: ChannelPolicy(managed=True, can_leave=False, can_rename=False, can_invite=False),
        Kind.WORKGROUP: ChannelPolicy(managed=True, can_leave=False, can_rename=False, can_invite=False),
    }

    kind = models.CharField(max_length=255, choices=Kind.choices)
    title = models.CharField(max_length=255, null=True, blank=True, validators=[FieldNotBlankValidator])
    # "<lowest user id>:<highest user id>" for direct messages, so each pair of users has at most one
    dm_key = models.CharField(max_length=64, null=True, blank=True, unique=True)
    users = models.ManyToManyField('user.User', through='chat.MessageChannelParticipant',
                                   through_fields=('channel', 'user'))

    @property
    def policy(self) -> ChannelPolicy:
        return self.POLICIES[self.Kind(self.kind)]

    @staticmethod
    def make_dm_key(user_id: int, other_user_id: int) -> str:
        return ':'.join(str(i) for i in sorted([user_id, other_user_id]))


# Allows for "channels" inside a group
class MessageChannelTopic(BaseModel):
    channel = models.ForeignKey(MessageChannel, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, validators=[FieldNotBlankValidator])
    hidden = models.BooleanField(default=False)


class MessageChannelParticipant(BaseModel):
    """A user's membership of a chat. Only active members can read and send messages."""
    class Status(models.TextChoices):
        INVITED = 'invited', 'Invited'
        ACTIVE = 'active', 'Active'
        DECLINED = 'declined', 'Declined'
        LEFT = 'left', 'Left'

    user = models.ForeignKey('user.User', on_delete=models.CASCADE)
    channel = models.ForeignKey(MessageChannel, on_delete=models.CASCADE)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    invited_by = models.ForeignKey('user.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    last_read_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE

    class Meta:
        unique_together = ('user', 'channel')


# For image attachments
class MessageFileCollection(BaseModel):
    user = models.ForeignKey('user.User', on_delete=models.CASCADE)
    channel = models.ForeignKey(MessageChannel, on_delete=models.CASCADE)
    file_collection = models.ForeignKey(FileCollection, on_delete=models.CASCADE)

    ATTACHMENTS_UPLOAD_TO = 'message'


class Message(BaseModel):
    class Type(models.TextChoices):
        MESSAGE = 'message', 'Message'
        INFO = 'info', 'Info'  # Written by the system, e.g. when someone joins

    class Event(models.TextChoices):
        JOINED = 'joined', 'Joined'
        LEFT = 'left', 'Left'
        RENAMED = 'renamed', 'Renamed'

    user = models.ForeignKey('user.User', on_delete=models.CASCADE)
    channel = models.ForeignKey(MessageChannel, on_delete=models.CASCADE)
    type = models.CharField(max_length=255, choices=Type.choices, default=Type.MESSAGE)
    # What happened, for info messages
    event = models.CharField(max_length=32, choices=Event.choices, null=True, blank=True)
    topic = models.ForeignKey(MessageChannelTopic, on_delete=models.CASCADE, null=True, blank=True)
    message = models.TextField(max_length=2000, validators=[FieldNotBlankValidator])
    attachments = models.ForeignKey(MessageFileCollection,
                                    on_delete=models.SET_NULL,
                                    null=True,
                                    blank=True)  # TODO instead of MessageFileCollection, use FileCollection directly
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='message_parent')
    active = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=['channel', '-id'], name='chat_message_channel_id_idx')]
