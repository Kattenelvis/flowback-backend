from rest_framework.test import APITestCase

from flowback.common.tests import generate_request
from flowback.group.tests.factories import GroupFactory, GroupThreadFactory, GroupUserFactory
from flowback.group.views.thread import GroupThreadListAPI
from flowback.poll.models import Poll
from flowback.poll.tasks import poll_proposal_archive_check
from flowback.poll.tests.factories import PollFactory, PollProposalFactory
from flowback.poll.tests.utils import generate_poll_phase_kwargs
from flowback.poll.views.poll import PollListApi
from flowback.user.views.home import UserHomeFeedAPI


class PollArchiveTaskTest(APITestCase):
    def setUp(self):
        self.group = GroupFactory()
        self.group_user = GroupUserFactory(group=self.group)

    def create_poll(self, phase: str, **kwargs) -> Poll:
        return PollFactory(created_by=self.group_user, **generate_poll_phase_kwargs(phase), **kwargs)

    def test_poll_without_proposals_is_archived_after_proposal_phase(self):
        poll = self.create_poll('prediction_statement')

        poll_proposal_archive_check(poll_id=poll.id)

        poll.refresh_from_db()
        self.assertTrue(poll.is_archived)

    def test_poll_is_not_archived_by_default(self):
        poll = self.create_poll('proposal')

        self.assertFalse(poll.is_archived)

    def test_poll_with_proposal_is_not_archived(self):
        poll = self.create_poll('prediction_statement')
        PollProposalFactory(poll=poll, created_by=self.group_user)

        poll_proposal_archive_check(poll_id=poll.id)

        poll.refresh_from_db()
        self.assertFalse(poll.is_archived)

    def test_poll_with_only_removed_proposals_is_archived(self):
        poll = self.create_poll('prediction_statement')
        PollProposalFactory(poll=poll, created_by=self.group_user, active=False)

        poll_proposal_archive_check(poll_id=poll.id)

        poll.refresh_from_db()
        self.assertTrue(poll.is_archived)

    def test_poll_is_not_archived_while_proposal_phase_is_ongoing(self):
        poll = self.create_poll('proposal')

        poll_proposal_archive_check(poll_id=poll.id)

        poll.refresh_from_db()
        self.assertFalse(poll.is_archived)

    def test_dynamic_poll_is_not_archived(self):
        poll = self.create_poll('prediction_statement', dynamic=True)

        poll_proposal_archive_check(poll_id=poll.id)

        poll.refresh_from_db()
        self.assertFalse(poll.is_archived)

    def test_deleted_poll_is_not_archived(self):
        poll = self.create_poll('prediction_statement', active=False)

        poll_proposal_archive_check(poll_id=poll.id)

        poll.refresh_from_db()
        self.assertFalse(poll.is_archived)

    def test_unknown_poll_is_ignored(self):
        poll_proposal_archive_check(poll_id=0)


class ArchivedListTest(APITestCase):
    def setUp(self):
        self.group = GroupFactory()
        self.group_user = self.group.group_user_creator
        self.user = self.group_user.user

        self.poll = PollFactory(created_by=self.group_user, **generate_poll_phase_kwargs('proposal'))
        self.archived_poll = PollFactory(created_by=self.group_user,
                                         is_archived=True,
                                         **generate_poll_phase_kwargs('prediction_statement'))
        self.thread = GroupThreadFactory(created_by=self.group_user)
        self.archived_thread = GroupThreadFactory(created_by=self.group_user, is_archived=True)

    @staticmethod
    def ids(response) -> set[int]:
        return {result['id'] for result in response.data['results']}

    def test_poll_list_hides_archived_by_default(self):
        response = generate_request(api=PollListApi, user=self.user)

        self.assertEqual(self.ids(response), {self.poll.id})
        self.assertFalse(response.data['results'][0]['is_archived'])

    def test_poll_list_returns_only_archived_when_requested(self):
        response = generate_request(api=PollListApi, data=dict(is_archived=True), user=self.user)

        self.assertEqual(self.ids(response), {self.archived_poll.id})
        self.assertTrue(response.data['results'][0]['is_archived'])

    def test_poll_list_returns_archived_poll_when_looked_up_by_id(self):
        response = generate_request(api=PollListApi, data=dict(id=self.archived_poll.id), user=self.user)

        self.assertEqual(self.ids(response), {self.archived_poll.id})

    def test_poll_list_returns_archived_poll_when_looked_up_by_id_list(self):
        response = generate_request(api=PollListApi,
                                    data=dict(id_list=f'{self.poll.id},{self.archived_poll.id}'),
                                    user=self.user)

        self.assertEqual(self.ids(response), {self.poll.id, self.archived_poll.id})

    def test_thread_list_hides_archived_by_default(self):
        response = generate_request(api=GroupThreadListAPI, user=self.user)

        self.assertEqual(self.ids(response), {self.thread.id})
        self.assertFalse(response.data['results'][0]['is_archived'])

    def test_thread_list_returns_only_archived_when_requested(self):
        response = generate_request(api=GroupThreadListAPI, data=dict(is_archived=True), user=self.user)

        self.assertEqual(self.ids(response), {self.archived_thread.id})

    def test_thread_list_returns_archived_thread_when_looked_up_by_id(self):
        response = generate_request(api=GroupThreadListAPI, data=dict(id=self.archived_thread.id), user=self.user)

        self.assertEqual(self.ids(response), {self.archived_thread.id})

    def feed(self, **data) -> set[tuple[str, int]]:
        response = generate_request(api=UserHomeFeedAPI, data=data, user=self.user)
        self.assertEqual(response.status_code, 200)
        return {(result['related_model'], result['id']) for result in response.data['results']}

    def test_home_feed_hides_archived_by_default(self):
        self.assertEqual(self.feed(), {('poll', self.poll.id), ('thread', self.thread.id)})

    def test_home_feed_returns_only_archived_when_requested(self):
        self.assertEqual(self.feed(is_archived=True),
                         {('poll', self.archived_poll.id), ('thread', self.archived_thread.id)})

    def test_home_feed_returns_archived_post_when_looked_up_by_id(self):
        self.assertEqual(self.feed(id=self.archived_poll.id), {('poll', self.archived_poll.id)})
