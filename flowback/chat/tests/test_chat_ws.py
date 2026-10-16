import asyncio

from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.test import override_settings
from knox.models import AuthToken
from rest_framework.test import APITransactionTestCase

from backend.middleware import TokenAuthMiddleware
from flowback.chat.consumers import ChatConsumer
from flowback.chat.services import (group_chat_create, channel_invite_accept, channel_leave, channel_rename,
                                    direct_channel_get_or_create)
from flowback.group.tests.factories import GroupFactory, GroupUserFactory
from flowback.user.models import User
from flowback.user.tests.factories import UserFactory


@override_settings(CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}})
class ChatWebsocketTest(APITransactionTestCase):
    def setUp(self):
        self.creator = UserFactory()
        self.member = UserFactory()
        self.invitee = UserFactory()
        self.channel = group_chat_create(user=self.creator, title="Chat",
                                         user_ids=[self.member.id, self.invitee.id])
        channel_invite_accept(user=self.member, channel_id=self.channel.id)

    @sync_to_async
    def get_auth_token(self, user: User):
        instance, token = AuthToken.objects.create(user=user)
        return token

    async def connect(self, user: User) -> WebsocketCommunicator:
        token = await self.get_auth_token(user=user)
        communicator = WebsocketCommunicator(TokenAuthMiddleware(ChatConsumer.as_asgi()), f"/chat/ws?token={token}")
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        return communicator

    async def receive_until(self, communicator: WebsocketCommunicator, event_type: str, text: str = None,
                            timeout=3) -> dict:
        """Skips other events until one of the given type (and message text) arrives."""
        while True:
            event = await communicator.receive_json_from(timeout=timeout)
            if event['type'] == event_type and (text is None or event['message']['message'] == text):
                return event

    async def send(self, communicator: WebsocketCommunicator, text: str, client_id: str = None, channel_id=None):
        await communicator.send_json_to(dict(method='message_create', channel_id=channel_id or self.channel.id,
                                             message=text, client_id=client_id))

    async def test_messages_reach_active_members_only(self):
        creator = await self.connect(self.creator)
        member = await self.connect(self.member)
        invitee = await self.connect(self.invitee)

        await self.send(creator, "Hello", client_id="draft-1")

        own = await self.receive_until(creator, 'message.created')
        self.assertEqual(own['client_id'], "draft-1")
        self.assertEqual(own['message']['message'], "Hello")

        received = await self.receive_until(member, 'message.created')
        self.assertEqual(received['message']['message'], "Hello")
        self.assertEqual(received['message']['user']['id'], self.creator.id)

        self.assertTrue(await invitee.receive_nothing(timeout=0.3))

        for communicator in [creator, member, invitee]:
            await communicator.disconnect()

    async def test_accepting_an_invite_subscribes_without_reconnecting(self):
        creator = await self.connect(self.creator)
        invitee = await self.connect(self.invitee)

        await sync_to_async(channel_invite_accept)(user=self.invitee, channel_id=self.channel.id)
        added = await self.receive_until(invitee, 'channel.added')
        self.assertEqual(added['channel']['id'], self.channel.id)
        self.assertEqual(added['channel']['status'], 'active')

        await self.send(creator, "Welcome")
        await self.receive_until(invitee, 'message.created', "Welcome")

        await creator.disconnect()
        await invitee.disconnect()

    async def test_leaving_stops_messages(self):
        creator = await self.connect(self.creator)
        member = await self.connect(self.member)

        await sync_to_async(channel_leave)(user=self.member, channel_id=self.channel.id)
        removed = await self.receive_until(member, 'channel.removed')
        self.assertEqual(removed['channel_id'], self.channel.id)

        left = await self.receive_until(creator, 'message.created')
        self.assertEqual(left['message']['event'], 'left')
        updated = await self.receive_until(creator, 'channel.updated')
        self.assertEqual(updated['member_count'], 1)

        await asyncio.sleep(0.1)  # Let the unsubscribe reach the member's socket
        while not await member.receive_nothing(timeout=0.1):
            await member.receive_json_from()

        await self.send(creator, "Are you there?")
        await self.receive_until(creator, 'message.created', "Are you there?")
        self.assertTrue(await member.receive_nothing(timeout=0.3))

        await creator.disconnect()
        await member.disconnect()

    async def test_rename_reaches_members(self):
        member = await self.connect(self.member)

        await sync_to_async(channel_rename)(user=self.creator, channel_id=self.channel.id, title="New name")
        updated = await self.receive_until(member, 'channel.updated')
        self.assertEqual(updated['title'], "New name")

        await member.disconnect()

    async def test_joining_a_group_mid_session_receives_its_chat(self):
        group = await sync_to_async(GroupFactory)(created_by=self.creator)
        creator = await self.connect(self.creator)
        member = await self.connect(self.member)

        await sync_to_async(GroupUserFactory)(group=group, user=self.member)
        await self.receive_until(member, 'channel.added')

        await self.send(creator, "Hi group", channel_id=group.chat_id)
        await self.receive_until(member, 'message.created', "Hi group")

        await creator.disconnect()
        await member.disconnect()

    async def test_new_direct_message_reaches_the_other_person(self):
        stranger = await sync_to_async(UserFactory)(chat_status=User.PublicStatus.PUBLIC)
        receiver = await self.connect(stranger)
        sender = await self.connect(self.creator)

        channel = await sync_to_async(direct_channel_get_or_create)(user=self.creator, target_user_id=stranger.id)
        added = await self.receive_until(receiver, 'channel.added')
        self.assertEqual(added['channel']['title'], self.creator.username)

        await self.send(sender, "First message", channel_id=channel.id)
        await self.receive_until(receiver, 'message.created', "First message")

        await sender.disconnect()
        await receiver.disconnect()

    async def test_errors_keep_the_socket_open(self):
        invitee = await self.connect(self.invitee)

        await self.send(invitee, "Can I talk yet?", client_id="draft-2")
        error = await self.receive_until(invitee, 'error')
        self.assertEqual(error['client_id'], "draft-2")
        self.assertEqual(error['method'], 'message_create')

        await invitee.send_to(text_data="not json")
        await self.receive_until(invitee, 'error')

        await invitee.send_json_to(dict(method='no_such_method'))
        await self.receive_until(invitee, 'error')

        await invitee.disconnect()

    async def test_too_long_messages_get_a_clear_error(self):
        member = await self.connect(self.member)

        await self.send(member, "x" * 2001, client_id="draft-3")
        error = await self.receive_until(member, 'error')
        self.assertEqual(error['client_id'], "draft-3")
        self.assertIn('message', error['detail'])

        await member.disconnect()

    async def test_anonymous_users_are_rejected(self):
        communicator = WebsocketCommunicator(TokenAuthMiddleware(ChatConsumer.as_asgi()), "/chat/ws")
        connected, _ = await communicator.connect()
        self.assertFalse(connected)
