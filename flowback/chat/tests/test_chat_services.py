from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from flowback.chat.models import MessageChannel, MessageChannelParticipant, Message
from flowback.chat.selectors import channel_list, channel_summaries, message_list
from flowback.chat.services import (direct_channel_get_or_create, group_chat_create, channel_invite,
                                    channel_invite_accept, channel_invite_decline, channel_leave, channel_rename,
                                    channel_mark_read, message_create, message_update, message_delete)
from flowback.chat.tests.factories import MessageChannelFactory, MessageChannelParticipantFactory
from flowback.group.services.group import group_leave
from flowback.group.tests.factories import GroupFactory, GroupUserFactory, WorkGroupFactory, WorkGroupUserFactory
from flowback.user.models import User
from flowback.user.tests.factories import UserFactory

Status = MessageChannelParticipant.Status
Kind = MessageChannel.Kind


def status_of(user, channel) -> str | None:
    participant = MessageChannelParticipant.objects.filter(user=user, channel=channel).first()
    return participant.status if participant else None


def summaries_for(user, **filters) -> dict[int, dict]:
    participants = list(channel_list(user=user, filters=filters))
    return {s['id']: s for s in channel_summaries(user=user, participants=participants)}


class DirectMessageTest(APITestCase):
    def setUp(self):
        self.user = UserFactory()
        self.public_user = UserFactory(chat_status=User.PublicStatus.PUBLIC)
        self.private_user = UserFactory(chat_status=User.PublicStatus.PRIVATE)
        self.group_only_user = UserFactory(chat_status=User.PublicStatus.GROUP_ONLY)

    def test_public_user_joins_straight_away(self):
        channel = direct_channel_get_or_create(user=self.user, target_user_id=self.public_user.id)

        self.assertEqual(channel.kind, Kind.USER)
        self.assertEqual(status_of(self.user, channel), Status.ACTIVE)
        self.assertEqual(status_of(self.public_user, channel), Status.ACTIVE)

    def test_one_channel_per_pair_of_users(self):
        first = direct_channel_get_or_create(user=self.user, target_user_id=self.public_user.id)
        again = direct_channel_get_or_create(user=self.user, target_user_id=self.public_user.id)
        reverse = direct_channel_get_or_create(user=self.public_user, target_user_id=self.user.id)

        self.assertEqual(first.id, again.id)
        self.assertEqual(first.id, reverse.id)
        self.assertEqual(MessageChannel.objects.filter(kind=Kind.USER).count(), 1)

    def test_private_user_is_invited_and_accepts_by_opening_it(self):
        channel = direct_channel_get_or_create(user=self.user, target_user_id=self.private_user.id)
        self.assertEqual(status_of(self.private_user, channel), Status.INVITED)

        direct_channel_get_or_create(user=self.private_user, target_user_id=self.user.id)
        self.assertEqual(status_of(self.private_user, channel), Status.ACTIVE)

    def test_declined_user_is_not_invited_again(self):
        channel = direct_channel_get_or_create(user=self.user, target_user_id=self.private_user.id)
        channel_invite_decline(user=self.private_user, channel_id=channel.id)

        direct_channel_get_or_create(user=self.user, target_user_id=self.private_user.id)
        self.assertEqual(status_of(self.private_user, channel), Status.DECLINED)

    def test_group_only_user_needs_a_shared_group(self):
        channel = direct_channel_get_or_create(user=self.user, target_user_id=self.group_only_user.id)
        self.assertEqual(status_of(self.group_only_user, channel), Status.INVITED)

        other = UserFactory()
        group = GroupFactory(created_by=other)  # The creator is added as a member
        GroupUserFactory(group=group, user=self.group_only_user)
        channel = direct_channel_get_or_create(user=other, target_user_id=self.group_only_user.id)
        self.assertEqual(status_of(self.group_only_user, channel), Status.ACTIVE)

    def test_cannot_message_yourself(self):
        with self.assertRaises(ValidationError):
            direct_channel_get_or_create(user=self.user, target_user_id=self.user.id)

    def test_cannot_leave_or_rename(self):
        channel = direct_channel_get_or_create(user=self.user, target_user_id=self.public_user.id)

        with self.assertRaises(ValidationError):
            channel_leave(user=self.user, channel_id=channel.id)

        with self.assertRaises(ValidationError):
            channel_rename(user=self.user, channel_id=channel.id, title="New name")

    def test_title_is_the_other_users_name(self):
        channel = direct_channel_get_or_create(user=self.user, target_user_id=self.public_user.id)

        self.assertEqual(summaries_for(self.user)[channel.id]['title'], self.public_user.username)
        self.assertEqual(summaries_for(self.public_user)[channel.id]['title'], self.user.username)


class GroupChatTest(APITestCase):
    def setUp(self):
        self.creator = UserFactory()
        self.member_one = UserFactory(chat_status=User.PublicStatus.PUBLIC)
        self.member_two = UserFactory()
        self.channel = group_chat_create(user=self.creator, title="Project",
                                         user_ids=[self.member_one.id, self.member_two.id])

    def accept_all(self):
        channel_invite_accept(user=self.member_one, channel_id=self.channel.id)
        channel_invite_accept(user=self.member_two, channel_id=self.channel.id)

    def test_creator_joins_and_everyone_else_is_invited(self):
        self.assertEqual(self.channel.kind, Kind.USER_GROUP)
        self.assertEqual(self.channel.title, "Project")
        self.assertEqual(status_of(self.creator, self.channel), Status.ACTIVE)
        self.assertEqual(status_of(self.member_one, self.channel), Status.INVITED)
        self.assertEqual(status_of(self.member_two, self.channel), Status.INVITED)

        invite = MessageChannelParticipant.objects.get(user=self.member_one, channel=self.channel)
        self.assertEqual(invite.invited_by, self.creator)

    def test_same_members_make_a_new_chat(self):
        other = group_chat_create(user=self.creator, title="Another project",
                                  user_ids=[self.member_one.id, self.member_two.id])

        self.assertNotEqual(other.id, self.channel.id)
        self.assertEqual(other.title, "Another project")

    def test_two_person_group_chat_is_still_a_group_chat(self):
        channel = group_chat_create(user=self.creator, user_ids=[self.member_one.id])

        self.assertEqual(channel.kind, Kind.USER_GROUP)
        self.assertEqual(status_of(self.member_one, channel), Status.INVITED)

    def test_needs_other_members(self):
        with self.assertRaises(ValidationError):
            group_chat_create(user=self.creator, title="Alone", user_ids=[self.creator.id])

    def test_title_defaults_to_member_names(self):
        channel = group_chat_create(user=self.creator, title="  ", user_ids=[self.member_one.id])

        self.assertIn(self.creator.username, channel.title)
        self.assertIn(self.member_one.username, channel.title)

    def test_accepting_an_invite_joins(self):
        channel_invite_accept(user=self.member_one, channel_id=self.channel.id)

        self.assertEqual(status_of(self.member_one, self.channel), Status.ACTIVE)
        self.assertTrue(Message.objects.filter(channel=self.channel, user=self.member_one,
                                               event=Message.Event.JOINED).exists())

        with self.assertRaises(ValidationError):
            channel_invite_accept(user=self.member_one, channel_id=self.channel.id)

    def test_declining_an_invite(self):
        channel_invite_decline(user=self.member_one, channel_id=self.channel.id)

        self.assertEqual(status_of(self.member_one, self.channel), Status.DECLINED)
        self.assertNotIn(self.channel.id, summaries_for(self.member_one))

    def test_leaving_keeps_the_chat_for_everyone_else(self):
        self.accept_all()
        message_create(user_id=self.creator.id, channel_id=self.channel.id, message="Hello")

        channel_leave(user=self.member_one, channel_id=self.channel.id)

        self.assertTrue(MessageChannel.objects.filter(id=self.channel.id).exists())
        self.assertEqual(status_of(self.member_one, self.channel), Status.LEFT)
        self.assertEqual(status_of(self.creator, self.channel), Status.ACTIVE)
        self.assertEqual(status_of(self.member_two, self.channel), Status.ACTIVE)
        self.assertTrue(Message.objects.filter(channel=self.channel, message="Hello").exists())
        self.assertTrue(Message.objects.filter(channel=self.channel, user=self.member_one,
                                               event=Message.Event.LEFT).exists())
        self.assertNotIn(self.channel.id, summaries_for(self.member_one))

    def test_left_members_cannot_read_or_send(self):
        self.accept_all()
        channel_leave(user=self.member_one, channel_id=self.channel.id)

        with self.assertRaises(ValidationError):
            message_create(user_id=self.member_one.id, channel_id=self.channel.id, message="Still here?")

        with self.assertRaises(ValidationError):
            message_list(user=self.member_one, channel_id=self.channel.id)

    def test_invited_members_cannot_read_or_send(self):
        with self.assertRaises(ValidationError):
            message_create(user_id=self.member_one.id, channel_id=self.channel.id, message="Hi")

        with self.assertRaises(ValidationError):
            message_list(user=self.member_one, channel_id=self.channel.id)

    def test_chat_is_deleted_when_the_last_member_leaves(self):
        channel_leave(user=self.creator, channel_id=self.channel.id)

        self.assertFalse(MessageChannel.objects.filter(id=self.channel.id).exists())

    def test_members_can_invite_more_people(self):
        self.accept_all()
        newcomer = UserFactory()
        channel_leave(user=self.member_two, channel_id=self.channel.id)

        channel_invite(user=self.member_one, channel_id=self.channel.id, user_ids=[newcomer.id, self.member_two.id])

        self.assertEqual(status_of(newcomer, self.channel), Status.INVITED)
        self.assertEqual(status_of(self.member_two, self.channel), Status.INVITED)

    def test_outsiders_cannot_invite(self):
        with self.assertRaises(ValidationError):
            channel_invite(user=self.member_one, channel_id=self.channel.id, user_ids=[UserFactory().id])

    def test_rename(self):
        channel_rename(user=self.creator, channel_id=self.channel.id, title="  Renamed  ")

        self.channel.refresh_from_db()
        self.assertEqual(self.channel.title, "Renamed")
        self.assertTrue(Message.objects.filter(channel=self.channel, event=Message.Event.RENAMED).exists())

        with self.assertRaises(ValidationError):
            channel_rename(user=self.creator, channel_id=self.channel.id, title="   ")

    def test_capabilities(self):
        creator_view = summaries_for(self.creator)[self.channel.id]
        invitee_view = summaries_for(self.member_one)[self.channel.id]

        self.assertTrue(creator_view['can_leave'] and creator_view['can_rename'] and creator_view['can_invite'])
        self.assertEqual(invitee_view['status'], Status.INVITED)
        self.assertFalse(invitee_view['can_leave'] or invitee_view['can_rename'] or invitee_view['can_invite'])
        self.assertIsNone(invitee_view['last_message'])
        self.assertEqual(invitee_view['invited_by'], self.creator)


class ManagedChatTest(APITestCase):
    def setUp(self):
        self.group = GroupFactory()
        self.user = UserFactory()

    def test_group_members_follow_group_membership(self):
        group_user = GroupUserFactory(group=self.group, user=self.user)
        self.assertEqual(status_of(self.user, self.group.chat), Status.ACTIVE)

        group_leave(user=self.user.id, group=self.group.id)
        self.assertEqual(status_of(self.user, self.group.chat), Status.LEFT)

        group_user.refresh_from_db()
        group_user.active = True
        group_user.save(update_fields=['active'])
        self.assertEqual(status_of(self.user, self.group.chat), Status.ACTIVE)

    def test_members_cannot_leave_or_rename_group_chats(self):
        GroupUserFactory(group=self.group, user=self.user)

        with self.assertRaises(ValidationError):
            channel_leave(user=self.user, channel_id=self.group.chat.id)

        with self.assertRaises(ValidationError):
            channel_rename(user=self.user, channel_id=self.group.chat.id, title="Mine now")

    def test_renaming_the_group_renames_its_chat(self):
        self.group.name = "Renamed group"
        self.group.save(update_fields=['name'])

        self.group.chat.refresh_from_db()
        self.assertEqual(self.group.chat.title, "Renamed group")

    def test_deleting_the_group_deletes_its_chats(self):
        GroupUserFactory(group=self.group, user=self.user)
        work_group = WorkGroupFactory(group=self.group)
        chat_ids = [self.group.chat_id, work_group.chat_id]

        self.group.delete()

        self.assertFalse(MessageChannel.objects.filter(id__in=chat_ids).exists())

    def test_rejoining_through_an_invite_restores_the_chats(self):
        from flowback.group.models import GroupUserInvite
        from flowback.group.services.invite import group_invite_accept

        group_user = GroupUserFactory(group=self.group, user=self.user)
        work_group_user = WorkGroupUserFactory(group_user=group_user)
        work_group_chat = work_group_user.work_group.chat

        group_leave(user=self.user.id, group=self.group.id)
        self.assertEqual(status_of(self.user, self.group.chat), Status.LEFT)
        self.assertEqual(status_of(self.user, work_group_chat), Status.LEFT)

        GroupUserInvite.objects.create(user=self.user, group=self.group, external=False)
        group_invite_accept(fetched_by=self.user.id, group=self.group.id)
        self.assertEqual(status_of(self.user, self.group.chat), Status.ACTIVE)
        self.assertEqual(status_of(self.user, work_group_chat), Status.ACTIVE)

    def test_deleting_a_group_does_not_post_left_messages(self):
        for _ in range(3):
            GroupUserFactory(group=self.group)
        chat_id = self.group.chat_id
        work_group_chat_id = WorkGroupFactory(group=self.group).chat_id
        before = Message.objects.filter(event=Message.Event.LEFT).count()

        self.group.delete()

        self.assertEqual(Message.objects.filter(event=Message.Event.LEFT).count(), before)
        self.assertFalse(MessageChannel.objects.filter(id__in=[chat_id, work_group_chat_id]).exists())

    def test_renaming_a_work_group_renames_its_chat(self):
        from flowback.group.services.workgroup import work_group_update

        work_group = WorkGroupFactory(group=self.group)
        work_group_update(user_id=self.group.created_by_id, work_group_id=work_group.id, data=dict(name="New name"))

        work_group.chat.refresh_from_db()
        self.assertEqual(work_group.chat.title, "New name")

    def test_work_group_chat_follows_membership_and_is_deleted_with_it(self):
        group_user = GroupUserFactory(group=self.group, user=self.user)
        work_group_user = WorkGroupUserFactory(group_user=group_user)
        channel = work_group_user.work_group.chat
        self.assertEqual(status_of(self.user, channel), Status.ACTIVE)

        work_group_user.delete()
        self.assertEqual(status_of(self.user, channel), Status.LEFT)

        work_group_user.work_group.delete()
        self.assertFalse(MessageChannel.objects.filter(id=channel.id).exists())


class ChannelListTest(APITestCase):
    def setUp(self):
        self.user = UserFactory()
        self.friend = UserFactory(username='friendlyname', chat_status=User.PublicStatus.PUBLIC)
        self.dm = direct_channel_get_or_create(user=self.user, target_user_id=self.friend.id)
        self.group_chat = group_chat_create(user=self.user, title="Book club", user_ids=[self.friend.id])
        channel_invite_accept(user=self.friend, channel_id=self.group_chat.id)

    def test_most_recent_activity_first(self):
        message_create(user_id=self.friend.id, channel_id=self.dm.id, message="Newest")

        ids = list(summaries_for(self.user).keys())
        self.assertEqual(ids[0], self.dm.id)

        message_create(user_id=self.friend.id, channel_id=self.group_chat.id, message="Even newer")

        ids = list(summaries_for(self.user).keys())
        self.assertEqual(ids[0], self.group_chat.id)

    def test_unread_count_and_mark_read(self):
        message_create(user_id=self.friend.id, channel_id=self.dm.id, message="One")
        message_create(user_id=self.friend.id, channel_id=self.dm.id, message="Two")
        message_create(user_id=self.user.id, channel_id=self.dm.id, message="Mine")

        # Sending a message counts as reading the chat
        self.assertEqual(summaries_for(self.user)[self.dm.id]['unread_count'], 0)
        self.assertEqual(summaries_for(self.friend)[self.dm.id]['unread_count'], 1)

        message_create(user_id=self.user.id, channel_id=self.dm.id, message="Another")
        self.assertEqual(summaries_for(self.friend)[self.dm.id]['unread_count'], 2)

        channel_mark_read(user=self.friend, channel_id=self.dm.id)
        self.assertEqual(summaries_for(self.friend)[self.dm.id]['unread_count'], 0)

    def test_info_messages_are_not_unread(self):
        newcomer = UserFactory()
        channel_invite(user=self.user, channel_id=self.group_chat.id, user_ids=[newcomer.id])
        channel_invite_accept(user=newcomer, channel_id=self.group_chat.id)

        self.assertEqual(summaries_for(self.user)[self.group_chat.id]['unread_count'], 0)

    def test_last_message_and_member_count(self):
        message_create(user_id=self.friend.id, channel_id=self.group_chat.id, message="Latest")
        summary = summaries_for(self.user)[self.group_chat.id]

        self.assertEqual(summary['last_message'].message, "Latest")
        self.assertEqual(summary['member_count'], 2)

    def test_info_messages_bump_the_chat_but_are_not_its_preview(self):
        message_create(user_id=self.friend.id, channel_id=self.group_chat.id, message="Latest")
        message_create(user_id=self.friend.id, channel_id=self.dm.id, message="Newer, in the DM")

        newcomer = UserFactory()
        channel_invite(user=self.user, channel_id=self.group_chat.id, user_ids=[newcomer.id])
        channel_invite_accept(user=newcomer, channel_id=self.group_chat.id)

        summaries = summaries_for(self.user)
        self.assertEqual(list(summaries)[0], self.group_chat.id)
        self.assertEqual(summaries[self.group_chat.id]['last_message'].message, "Latest")

    def test_search(self):
        self.assertEqual(list(summaries_for(self.user, search='book')), [self.group_chat.id])
        self.assertEqual(list(summaries_for(self.user, search='friendly')), [self.dm.id])
        self.assertEqual(list(summaries_for(self.user, search='nothing like this')), [])

    def test_filter_by_status(self):
        invite = group_chat_create(user=self.friend, title="Invite", user_ids=[self.user.id])

        self.assertEqual(list(summaries_for(self.user, status='invited')), [invite.id])
        self.assertNotIn(invite.id, summaries_for(self.user, status='active'))


class MessageTest(APITestCase):
    def setUp(self):
        self.user = UserFactory()
        self.other = UserFactory()
        self.channel = MessageChannelFactory()
        MessageChannelParticipantFactory(channel=self.channel, user=self.user)
        MessageChannelParticipantFactory(channel=self.channel, user=self.other)

    def test_paging_backwards(self):
        messages = [message_create(user_id=self.user.id, channel_id=self.channel.id, message=f"Message {i}")
                    for i in range(5)]

        newest = list(message_list(user=self.user, channel_id=self.channel.id)[:2])
        self.assertEqual([m.id for m in newest], [messages[4].id, messages[3].id])

        older = list(message_list(user=self.user, channel_id=self.channel.id, filters=dict(before_id=newest[-1].id)))
        self.assertEqual([m.id for m in older], [m.id for m in reversed(messages[:3])])

    def test_only_the_author_can_edit_or_delete(self):
        message = message_create(user_id=self.user.id, channel_id=self.channel.id, message="Original")

        with self.assertRaises(ValidationError):
            message_update(user_id=self.other.id, message_id=message.id, message="Changed")

        with self.assertRaises(ValidationError):
            message_delete(user_id=self.other.id, message_id=message.id)

        updated_at = message.updated_at
        message_update(user_id=self.user.id, message_id=message.id, message="Changed")
        message.refresh_from_db()
        self.assertEqual(message.message, "Changed")
        self.assertGreater(message.updated_at, updated_at)  # Shown as "(edited)"

        message_delete(user_id=self.user.id, message_id=message.id)
        self.assertFalse(message_list(user=self.user, channel_id=self.channel.id).filter(id=message.id).exists())

    def test_parent_must_be_in_the_same_chat(self):
        elsewhere = MessageChannelFactory()
        MessageChannelParticipantFactory(channel=elsewhere, user=self.user)
        parent = message_create(user_id=self.user.id, channel_id=elsewhere.id, message="Elsewhere")

        with self.assertRaises(ValidationError):
            message_create(user_id=self.user.id, channel_id=self.channel.id, message="Reply", parent_id=parent.id)

    def test_attachments_must_be_your_own(self):
        from flowback.chat.tests.factories import MessageFileCollectionFactory
        attachments = MessageFileCollectionFactory(channel=self.channel, user=self.other)

        with self.assertRaises(ValidationError):
            message_create(user_id=self.user.id, channel_id=self.channel.id, message="Look",
                           attachments_id=attachments.id)
