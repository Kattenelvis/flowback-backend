"""
User Bookmark Test Suite

This test suite covers:
- UserBookmarkCreateAPI
- UserBookmarkDeleteAPI
- UserBookmark database constraints
- The bookmarked filter of UserHomeFeedAPI and poll_list
- The bookmarked field of the poll and thread list outputs
"""

from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.test import APITestCase

from flowback.common.tests import generate_request
from flowback.group.views.thread import GroupThreadListAPI
from flowback.group.tests.factories import GroupThreadFactory, GroupUserFactory
from flowback.poll.selectors.poll import poll_list
from flowback.poll.views.poll import PollListApi
from flowback.poll.tests.factories import PollFactory
from flowback.user.models import UserBookmark
from flowback.user.tests.factories import UserFactory
from flowback.user.views.home import UserHomeFeedAPI
from flowback.user.views.user import UserBookmarkCreateAPI, UserBookmarkDeleteAPI


class UserBookmarkAPITest(APITestCase):

    def setUp(self):
        self.group_user = GroupUserFactory()
        self.user = self.group_user.user
        self.poll = PollFactory(created_by=self.group_user)
        self.thread = GroupThreadFactory(created_by=self.group_user)

    def create(self, content_type, object_id, user=None):
        return generate_request(UserBookmarkCreateAPI,
                                data=dict(content_type=content_type, object_id=object_id),
                                user=user or self.user)

    def delete(self, content_type, object_id, user=None):
        return generate_request(UserBookmarkDeleteAPI,
                                data=dict(content_type=content_type, object_id=object_id),
                                user=user or self.user)

    def test_create_poll_bookmark(self):
        response = self.create('poll', self.poll.id)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        bookmark = UserBookmark.objects.get(user=self.user)
        self.assertEqual(bookmark.poll, self.poll)
        self.assertIsNone(bookmark.thread)

    def test_create_thread_bookmark(self):
        response = self.create('groupthread', self.thread.id)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        bookmark = UserBookmark.objects.get(user=self.user)
        self.assertEqual(bookmark.thread, self.thread)
        self.assertIsNone(bookmark.poll)

    def test_create_content_type_is_case_insensitive(self):
        response = self.create('GroupThread', self.thread.id)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_create_duplicate_is_rejected(self):
        self.create('poll', self.poll.id)
        response = self.create('poll', self.poll.id)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertEqual(UserBookmark.objects.filter(user=self.user).count(), 1)

    def test_same_object_can_be_bookmarked_by_different_users(self):
        other_user = UserFactory()

        self.assertEqual(self.create('poll', self.poll.id).status_code, status.HTTP_201_CREATED)
        self.assertEqual(self.create('poll', self.poll.id, user=other_user).status_code, status.HTTP_201_CREATED)

    def test_create_unknown_content_type(self):
        response = self.create('user', self.user.id)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertFalse(UserBookmark.objects.exists())

    def test_create_nonexistent_object(self):
        response = self.create('poll', self.poll.id + 1000)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.data)
        self.assertFalse(UserBookmark.objects.exists())

    def test_create_inactive_object(self):
        self.poll.active = False
        self.poll.save()

        response = self.create('poll', self.poll.id)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.data)

    def test_thread_id_does_not_resolve_to_poll(self):
        """A thread and a poll can share an id, the content_type decides which one is bookmarked"""
        self.thread.delete()
        thread = GroupThreadFactory(id=self.poll.id, created_by=self.group_user)

        self.create('groupthread', thread.id)

        bookmark = UserBookmark.objects.get(user=self.user)
        self.assertEqual(bookmark.thread, thread)
        self.assertIsNone(bookmark.poll)

    def test_delete_bookmark(self):
        self.create('poll', self.poll.id)
        self.create('groupthread', self.thread.id)

        response = self.delete('poll', self.poll.id)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(UserBookmark.objects.get(user=self.user).thread, self.thread)

    def test_delete_nonexistent_bookmark(self):
        response = self.delete('poll', self.poll.id)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.data)

    def test_delete_only_affects_own_bookmark(self):
        other_user = UserFactory()
        self.create('poll', self.poll.id)

        response = self.delete('poll', self.poll.id, user=other_user)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.data)
        self.assertTrue(UserBookmark.objects.filter(user=self.user, poll=self.poll).exists())

    def test_delete_unknown_content_type(self):
        response = self.delete('user', self.user.id)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)

    def test_deleting_target_removes_bookmark(self):
        self.create('poll', self.poll.id)
        self.create('groupthread', self.thread.id)

        self.poll.delete()
        self.assertEqual(UserBookmark.objects.get(user=self.user).thread, self.thread)

        self.thread.delete()
        self.assertFalse(UserBookmark.objects.exists())


class UserBookmarkConstraintTest(APITestCase):

    def setUp(self):
        group_user = GroupUserFactory()
        self.user = group_user.user
        self.poll = PollFactory(created_by=group_user)
        self.thread = GroupThreadFactory(created_by=group_user)

    def assert_rejected(self, **kwargs):
        with self.assertRaises(IntegrityError), transaction.atomic():
            UserBookmark.objects.create(user=self.user, **kwargs)

    def test_requires_a_target(self):
        self.assert_rejected()

    def test_rejects_multiple_targets(self):
        self.assert_rejected(poll=self.poll, thread=self.thread)

    def test_rejects_duplicates(self):
        UserBookmark.objects.create(user=self.user, poll=self.poll)
        UserBookmark.objects.create(user=self.user, thread=self.thread)

        self.assert_rejected(poll=self.poll)
        self.assert_rejected(thread=self.thread)


class UserBookmarkHomeFeedTest(APITestCase):

    def test_bookmarked_filter_separates_polls_and_threads_sharing_an_id(self):
        group_user = GroupUserFactory(group__public=False)
        poll = PollFactory(created_by=group_user)
        thread = GroupThreadFactory(id=poll.id, created_by=group_user)

        UserBookmark.objects.create(user=group_user.user, thread=thread)

        response = generate_request(UserHomeFeedAPI, user=group_user.user, data=dict(bookmarked=True))
        self.assertEqual([(i['related_model'], i['id']) for i in response.data['results']],
                         [('thread', thread.id)])

        response = generate_request(UserHomeFeedAPI, user=group_user.user, data=dict(bookmarked=False))
        self.assertEqual([(i['related_model'], i['id']) for i in response.data['results']],
                         [('poll', poll.id)])

        UserBookmark.objects.create(user=group_user.user, poll=poll)

        response = generate_request(UserHomeFeedAPI, user=group_user.user, data=dict(bookmarked=True))
        self.assertCountEqual([(i['related_model'], i['id']) for i in response.data['results']],
                              [('thread', thread.id), ('poll', poll.id)])


class UserBookmarkPollListTest(APITestCase):

    def test_bookmarked_filter(self):
        group_user = GroupUserFactory()
        bookmarked_poll, other_poll = PollFactory.create_batch(size=2, created_by=group_user)
        UserBookmark.objects.create(user=group_user.user, poll=bookmarked_poll)

        def poll_ids(bookmarked):
            polls = poll_list(fetched_by=group_user.user,
                              group_id=group_user.group.id,
                              filters=dict(bookmarked=bookmarked))
            return [poll.id for poll in polls]

        self.assertEqual(poll_ids(True), [bookmarked_poll.id])
        self.assertEqual(poll_ids(False), [other_poll.id])


class UserBookmarkListOutputTest(APITestCase):

    def test_poll_and_thread_lists_expose_bookmarked(self):
        group_user = GroupUserFactory()
        poll = PollFactory(created_by=group_user)
        thread = GroupThreadFactory(created_by=group_user)

        def bookmarked(api, **kwargs):
            response = generate_request(api, user=group_user.user, **kwargs)
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
            return [result['bookmarked'] for result in response.data['results']]

        self.assertEqual(bookmarked(PollListApi), [False])
        self.assertEqual(bookmarked(GroupThreadListAPI), [False])

        UserBookmark.objects.create(user=group_user.user, poll=poll)
        UserBookmark.objects.create(user=group_user.user, thread=thread)

        self.assertEqual(bookmarked(PollListApi), [True])
        self.assertEqual(bookmarked(GroupThreadListAPI), [True])
