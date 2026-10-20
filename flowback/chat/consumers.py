"""The chat websocket.

Clients send {"method": ..., ...} and receive {"type": ..., ...} events:

    message_create   {channel_id, message, client_id?, parent_id?, topic_id?, attachments_id?}
    message_update   {message_id, message}
    message_delete   {message_id}

    message.created  {channel_id, message, client_id?}
    message.updated  {channel_id, message}
    message.deleted  {channel_id, message_id}
    channel.added    {channel}       Joined, or invited to, a chat
    channel.updated  {channel_id, title, member_count}
    channel.removed  {channel_id}    Left, declined, removed, or the chat was deleted
    channel.read     {channel_id}    Read in another tab
    error            {method, detail, client_id?}

Everything except errors is sent by flowback.chat.realtime, so actions taken over HTTP reach
clients the same way as ones taken here.
"""
import json
import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from flowback.chat import realtime
from flowback.chat.models import MessageChannelParticipant
from flowback.chat.services import message_create, message_update, message_delete

logger = logging.getLogger(__name__)


class MessageCreateSerializer(serializers.Serializer):
    channel_id = serializers.IntegerField()
    message = serializers.CharField(max_length=2000)
    client_id = serializers.CharField(required=False, allow_null=True, max_length=64)
    attachments_id = serializers.IntegerField(required=False)
    parent_id = serializers.IntegerField(required=False)
    topic_id = serializers.IntegerField(required=False)


class MessageUpdateSerializer(serializers.Serializer):
    message_id = serializers.IntegerField()
    message = serializers.CharField(max_length=2000)


class MessageDeleteSerializer(serializers.Serializer):
    message_id = serializers.IntegerField()


METHODS = {
    'message_create': (MessageCreateSerializer, message_create),
    'message_update': (MessageUpdateSerializer, message_update),
    'message_delete': (MessageDeleteSerializer, message_delete),
}


class ChatConsumer(AsyncJsonWebsocketConsumer):

    async def connect(self):
        self.user = self.scope['user']

        if self.user.is_anonymous:
            return await self.close()

        # Join the personal group first: membership changes made while the chats are being looked up then
        # queue a (un)subscribe that's handled once connect() finishes, instead of being missed
        user_group = realtime.user_group_name(self.user.id)
        await self.channel_layer.group_add(user_group, self.channel_name)
        self.groups_joined = {user_group}

        for channel_id in await self.get_active_channel_ids():
            group = realtime.channel_group_name(channel_id)
            self.groups_joined.add(group)
            await self.channel_layer.group_add(group, self.channel_name)

        await self.accept()

    async def disconnect(self, close_code):
        for group in getattr(self, 'groups_joined', set()):
            await self.channel_layer.group_discard(group, self.channel_name)

    @database_sync_to_async
    def get_active_channel_ids(self) -> list[int]:
        return list(MessageChannelParticipant.objects.filter(user=self.user,
                                                             status=MessageChannelParticipant.Status.ACTIVE)
                    .values_list('channel_id', flat=True))

    @classmethod
    async def decode_json(cls, text_data):
        try:
            return json.loads(text_data or '{}')
        except json.JSONDecodeError:
            return None

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict):
            return await self.send_error(method=None, detail="Messages must be JSON objects")

        method = content.get('method')
        if method not in METHODS:
            return await self.send_error(method=method, detail=f"Unknown method '{method}'")

        serializer_class, service = METHODS[method]
        try:
            serializer = serializer_class(data=content)
            serializer.is_valid(raise_exception=True)
            await database_sync_to_async(service)(user_id=self.user.id, **serializer.validated_data)

        except ValidationError as e:
            await self.send_error(method=method, detail=e.detail, client_id=content.get('client_id'))

        except DjangoValidationError as e:
            await self.send_error(method=method, detail=e.messages, client_id=content.get('client_id'))

        except Exception:  # Keep the socket open; the client shows the message as failed
            logger.exception("Chat websocket method %s failed", method)
            await self.send_error(method=method, detail="Something went wrong", client_id=content.get('client_id'))

    async def send_error(self, *, method: str | None, detail, client_id: str = None):
        error = dict(type='error', method=method, detail=detail)
        if client_id:
            error['client_id'] = client_id

        await self.send_json(error)

    # Channel layer handlers, called by flowback.chat.realtime

    async def chat_event(self, content: dict):
        await self.send_json(content['event'])

    async def chat_channel_event(self, content: dict):
        # Events queued before this socket unsubscribed from the chat
        if realtime.channel_group_name(content['channel_id']) in self.groups_joined:
            await self.send_json(content['event'])

    async def chat_subscribe(self, content: dict):
        group = realtime.channel_group_name(content['channel_id'])
        self.groups_joined.add(group)
        await self.channel_layer.group_add(group, self.channel_name)

    async def chat_unsubscribe(self, content: dict):
        group = realtime.channel_group_name(content['channel_id'])
        self.groups_joined.discard(group)
        await self.channel_layer.group_discard(group, self.channel_name)
