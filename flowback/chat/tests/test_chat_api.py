from rest_framework import status
from rest_framework.test import APITestCase

from flowback.chat.models import MessageChannel, MessageChannelParticipant
from flowback.chat.services import message_create
from flowback.chat.views import (ChannelListAPI, ChannelDetailAPI, DirectChannelAPI, GroupChatCreateAPI,
                                 ChannelInviteAPI, ChannelInviteAcceptAPI, ChannelInviteDeclineAPI, ChannelLeaveAPI,
                                 ChannelUpdateAPI, ChannelReadAPI, ChannelMemberListAPI, MessageListAPI)
from flowback.common.tests import generate_request
from flowback.user.models import User
from flowback.user.tests.factories import UserFactory

Status = MessageChannelParticipant.Status


class ChatAPITest(APITestCase):
    def setUp(self):
        self.user = UserFactory()
        self.friend = UserFactory(chat_status=User.PublicStatus.PUBLIC)
        self.stranger = UserFactory()

    def create_group_chat(self, title="Club", user_ids=None) -> dict:
        response = generate_request(api=GroupChatCreateAPI,
                                    data=dict(title=title, user_ids=user_ids or [self.friend.id]),
                                    user=self.user)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response.data

    def test_group_chat_lifecycle(self):
        channel = self.create_group_chat(user_ids=[self.friend.id, self.stranger.id])
        self.assertEqual(channel['kind'], 'user_group')
        self.assertEqual(channel['status'], 'active')
        self.assertTrue(channel['can_leave'])

        # The friend sees the invite in their list, and accepts it
        response = generate_request(api=ChannelListAPI, data=dict(status='invited'), user=self.friend)
        self.assertEqual([c['id'] for c in response.data['results']], [channel['id']])
        self.assertEqual(response.data['results'][0]['invited_by']['id'], self.user.id)

        response = generate_request(api=ChannelInviteAcceptAPI, url_params=dict(channel_id=channel['id']),
                                    user=self.friend)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['status'], 'active')

        # The stranger declines
        response = generate_request(api=ChannelInviteDeclineAPI, url_params=dict(channel_id=channel['id']),
                                    user=self.stranger)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        # Rename
        response = generate_request(api=ChannelUpdateAPI, url_params=dict(channel_id=channel['id']),
                                    data=dict(title="Renamed"), user=self.friend)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['title'], "Renamed")

        # Members
        response = generate_request(api=ChannelMemberListAPI, url_params=dict(channel_id=channel['id']),
                                    user=self.user)
        self.assertEqual({m['user']['id'] for m in response.data['results']}, {self.user.id, self.friend.id})

        # The friend leaves; the chat stays for the creator
        response = generate_request(api=ChannelLeaveAPI, url_params=dict(channel_id=channel['id']), user=self.friend)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        response = generate_request(api=ChannelDetailAPI, url_params=dict(channel_id=channel['id']), user=self.user)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['member_count'], 1)

        response = generate_request(api=ChannelDetailAPI, url_params=dict(channel_id=channel['id']),
                                    user=self.friend)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_group_chat_without_members_is_rejected(self):
        response = generate_request(api=GroupChatCreateAPI, data=dict(title="Alone", user_ids=[]), user=self.user)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invite_more_members(self):
        channel = self.create_group_chat()

        response = generate_request(api=ChannelInviteAPI, url_params=dict(channel_id=channel['id']),
                                    data=dict(user_ids=[self.stranger.id]), user=self.user)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(MessageChannelParticipant.objects.filter(channel_id=channel['id'], user=self.stranger,
                                                                 status=Status.INVITED).exists())

    def test_direct_message(self):
        response = generate_request(api=DirectChannelAPI, data=dict(user_id=self.friend.id), user=self.user)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['kind'], 'user')
        self.assertEqual(response.data['title'], self.friend.username)
        self.assertEqual(response.data['other_user']['id'], self.friend.id)
        self.assertFalse(response.data['can_leave'])

        again = generate_request(api=DirectChannelAPI, data=dict(user_id=self.friend.id), user=self.user)
        self.assertEqual(again.data['id'], response.data['id'])
        self.assertEqual(MessageChannel.objects.filter(kind='user').count(), 1)

    def test_messages_unread_and_read(self):
        response = generate_request(api=DirectChannelAPI, data=dict(user_id=self.friend.id), user=self.user)
        channel_id = response.data['id']
        messages = [message_create(user_id=self.friend.id, channel_id=channel_id, message=f"Hi {i}")
                    for i in range(3)]

        response = generate_request(api=ChannelListAPI, user=self.user)
        self.assertEqual(response.data['results'][0]['unread_count'], 3)
        self.assertEqual(response.data['results'][0]['last_message']['message'], "Hi 2")

        response = generate_request(api=MessageListAPI, url_params=dict(channel_id=channel_id),
                                    data=dict(limit=2), user=self.user)
        self.assertEqual([m['id'] for m in response.data['results']], [messages[2].id, messages[1].id])

        response = generate_request(api=MessageListAPI, url_params=dict(channel_id=channel_id),
                                    data=dict(before_id=messages[1].id), user=self.user)
        self.assertEqual([m['id'] for m in response.data['results'] if m['type'] == 'message'], [messages[0].id])

        response = generate_request(api=ChannelReadAPI, url_params=dict(channel_id=channel_id), user=self.user)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        response = generate_request(api=ChannelListAPI, user=self.user)
        self.assertEqual(response.data['results'][0]['unread_count'], 0)

    def test_non_members_cannot_read_messages(self):
        channel = self.create_group_chat()

        response = generate_request(api=MessageListAPI, url_params=dict(channel_id=channel['id']),
                                    user=self.stranger)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
