from rest_framework import status
from rest_framework.test import APITestCase

from flowback.common.tests import generate_request
from flowback.group.tests.factories import GroupFactory, GroupUserFactory, GroupThreadFactory
from flowback.poll.tests.factories import PollFactory
from flowback.server.views import ServerConfigListAPI, ServerReportListAPI
from flowback.user.tests.factories import UserFactory, ReportFactory


# Create your tests here.
class ServerTest(APITestCase):
    def test_get_public_config(self):
        response = generate_request(api=ServerConfigListAPI)
        print(response.data)

class ServerReportListTest(APITestCase):
    def setUp(self):
        self.group = GroupFactory()
        self.other_group = GroupFactory()
        self.group_admin = self.group.created_by
        self.member = GroupUserFactory(group=self.group).user
        self.staff = UserFactory(is_staff=True)

        self.poll = PollFactory(created_by__group=self.group)
        self.deleted_poll = PollFactory(created_by__group=self.group, active=False)
        self.thread = GroupThreadFactory(created_by__group=self.group)

        self.poll_report = ReportFactory(group_id=self.group.id, post_id=self.poll.id, post_type='poll')
        self.deleted_poll_report = ReportFactory(group_id=self.group.id,
                                                 post_id=self.deleted_poll.id,
                                                 post_type='poll')
        self.thread_report = ReportFactory(group_id=self.group.id, post_id=self.thread.id, post_type='thread')
        self.other_report = ReportFactory(group_id=self.other_group.id)

    def test_group_admin_lists_own_group_reports(self):
        response = generate_request(api=ServerReportListAPI, data=dict(group_id=self.group.id),
                                    user=self.group_admin)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 3)

        admin_actions = {report['id']: report['admin_action'] for report in response.data['results']}
        self.assertEqual(admin_actions[self.poll_report.id], 'nothing')
        self.assertEqual(admin_actions[self.thread_report.id], 'nothing')
        self.assertEqual(admin_actions[self.deleted_poll_report.id], 'deleted')

    def test_group_admin_cannot_list_other_group_reports(self):
        response = generate_request(api=ServerReportListAPI, data=dict(group_id=self.other_group.id),
                                    user=self.group_admin)
        self.assertNotEqual(response.status_code, status.HTTP_200_OK)

    def test_group_member_cannot_list_group_reports(self):
        response = generate_request(api=ServerReportListAPI, data=dict(group_id=self.group.id),
                                    user=self.member)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_group_admin_cannot_list_all_reports(self):
        response = generate_request(api=ServerReportListAPI, user=self.group_admin)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_lists_reports(self):
        response = generate_request(api=ServerReportListAPI, user=self.staff)
        self.assertEqual(response.data['count'], 4)

        response = generate_request(api=ServerReportListAPI, data=dict(group_id=self.other_group.id),
                                    user=self.staff)
        self.assertEqual(response.data['count'], 1)
