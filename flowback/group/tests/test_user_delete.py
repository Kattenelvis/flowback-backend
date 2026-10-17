from rest_framework import status
from rest_framework.test import APITestCase

from flowback.chat.models import MessageChannelParticipant
from flowback.common.tests import generate_request
from flowback.group.models import GroupUser, GroupThread
from flowback.group.selectors.permission import group_user_permissions
from flowback.group.services.group import group_join
from flowback.group.services.invite import group_invite_accept
from flowback.group.tests.factories import GroupFactory, GroupUserFactory, GroupThreadFactory, GroupUserInviteFactory
from flowback.group.views.group import GroupDetailApi
from flowback.group.views.thread import GroupThreadListAPI
from flowback.group.views.user import GroupUserDeleteAPI, GroupUserListApi
from flowback.kanban.models import KanbanSubscription
from flowback.notification.models import NotificationSubscription
from flowback.poll.models import Poll
from flowback.poll.tests.factories import PollFactory
from flowback.poll.views.poll import PollListApi


class GroupUserDeleteTest(APITestCase):
    def setUp(self):
        self.group = GroupFactory()
        self.group_admin = self.group.group_user_creator
        self.group_user = GroupUserFactory(group=self.group)
        self.other_group_user = GroupUserFactory(group=self.group)

        self.poll = PollFactory(created_by=self.group_user)
        self.thread = GroupThreadFactory(created_by=self.group_user)

    def kick(self, *, by=None, target=None):
        return generate_request(api=GroupUserDeleteAPI,
                                data=dict(target_user_id=(target or self.group_user).user.id),
                                url_params=dict(group_id=self.group.id),
                                user=(by or self.group_admin).user)

    def test_kick_deactivates_group_user(self):
        response = self.kick()
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        self.group_user.refresh_from_db()
        self.assertFalse(self.group_user.active)

    def test_kick_cleans_up_memberships(self):
        self.group.notification_channel.subscribe(user=self.group_user.user, tags=("group",))
        self.assertTrue(KanbanSubscription.objects.filter(kanban=self.group_user.user.kanban,
                                                          target=self.group.kanban).exists())

        self.kick()

        self.assertFalse(KanbanSubscription.objects.filter(kanban=self.group_user.user.kanban,
                                                           target=self.group.kanban).exists())
        self.assertFalse(MessageChannelParticipant.objects.get(id=self.group_user.chat_participant_id).active)
        self.assertFalse(NotificationSubscription.objects.filter(
            channel__in=self.group.notification_channel.descendants(include_self=True),
            user=self.group_user.user).exists())

    def test_kick_keeps_threads_and_polls(self):
        self.kick()

        self.assertTrue(GroupThread.objects.filter(id=self.thread.id, created_by=self.group_user).exists())
        self.assertTrue(Poll.objects.filter(id=self.poll.id, created_by=self.group_user).exists())

    def test_admin_still_sees_polls_and_threads_of_kicked_user(self):
        self.kick()

        poll_response = generate_request(api=PollListApi, user=self.group_admin.user)
        self.assertEqual(poll_response.status_code, status.HTTP_200_OK)
        self.assertIn(self.poll.id, [poll['id'] for poll in poll_response.data['results']])

        thread_response = generate_request(api=GroupThreadListAPI,
                                           data=dict(group_ids=str(self.group.id)),
                                           user=self.group_admin.user)
        self.assertEqual(thread_response.status_code, status.HTTP_200_OK)
        self.assertIn(self.thread.id, [thread['id'] for thread in thread_response.data['results']])

    def test_kicked_user_loses_access(self):
        self.kick()

        with self.assertRaises(GroupUser.DoesNotExist):
            group_user_permissions(user=self.group_user.user, group=self.group)

        poll_response = generate_request(api=PollListApi, user=self.group_user.user)
        self.assertEqual(poll_response.status_code, status.HTTP_200_OK)
        self.assertNotIn(self.poll.id, [poll['id'] for poll in poll_response.data['results']])

    def test_kicked_user_is_not_listed_as_member(self):
        self.kick()

        response = generate_request(api=GroupUserListApi,
                                    user=self.group_admin.user,
                                    url_params=dict(group_id=self.group.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(self.group_user.user.id, [group_user['user']['id'] for group_user in response.data['results']])

    def test_rejoin_restores_threads_and_polls(self):
        self.group.direct_join = True
        self.group.save()
        self.kick()

        group_join(user=self.group_user.user.id, group=self.group.id)

        rejoined = GroupUser.objects.get(user=self.group_user.user, group=self.group)
        self.assertEqual(rejoined.id, self.group_user.id)
        self.assertTrue(rejoined.active)
        self.assertTrue(MessageChannelParticipant.objects.get(id=rejoined.chat_participant_id).active)
        self.assertTrue(GroupThread.objects.filter(id=self.thread.id, created_by=rejoined).exists())
        self.assertTrue(Poll.objects.filter(id=self.poll.id, created_by=rejoined).exists())

    def test_rejoin_through_invite_reactivates_chat_participant(self):
        self.kick()

        GroupUserInviteFactory(group=self.group, user=self.group_user.user, external=False)
        group_invite_accept(fetched_by=self.group_user.user.id, group=self.group.id)

        rejoined = GroupUser.objects.get(user=self.group_user.user, group=self.group)
        self.assertEqual(rejoined.id, self.group_user.id)
        self.assertTrue(rejoined.active)
        self.assertTrue(MessageChannelParticipant.objects.get(id=rejoined.chat_participant_id).active)

    def test_non_admin_cannot_kick(self):
        response = self.kick(by=self.other_group_user)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.group_user.refresh_from_db()
        self.assertTrue(self.group_user.active)

    def test_cannot_kick_admin(self):
        response = self.kick(target=self.group_admin)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.group_admin.refresh_from_db()
        self.assertTrue(self.group_admin.active)

    def test_kick_decreases_member_count(self):
        def member_count():
            response = generate_request(api=GroupDetailApi,
                                        user=self.group_admin.user,
                                        url_params=dict(group=self.group.id))
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
            return response.data['member_count']

        before = member_count()
        self.kick()

        self.assertEqual(member_count(), before - 1)
