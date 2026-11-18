from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APITestCase

from flowback.common.tests import generate_request
from flowback.group.services.kanban import group_kanban_entry_change_group
from flowback.group.tests.factories import GroupFactory, GroupUserFactory, WorkGroupFactory, WorkGroupUserFactory
from flowback.group.views.kanban import GroupKanbanChangeGroupAPI
from flowback.kanban.models import KanbanEntry
from flowback.kanban.tests.factories import KanbanEntryFactory
from flowback.user.views.kanban import UserKanbanEntryListAPI


class TestKanban(APITestCase):
    def setUp(self):
        self.group_one = GroupFactory()
        self.group_two = GroupFactory()

        self.workgroup_one = WorkGroupFactory(group=self.group_one)
        self.workgroup_two = WorkGroupFactory(group=self.group_two)

        self.group_user_one = self.group_one.group_user_creator
        self.group_user_two = self.group_two.group_user_creator

        self.workgroupuser_one = WorkGroupUserFactory(group_user=self.group_user_one, work_group=self.workgroup_one)
        self.workgroupuser_two = WorkGroupUserFactory(group_user=self.group_user_two, work_group=self.workgroup_two)

    def test_kanban_list(self):
        kanbanentrieswg_one = KanbanEntryFactory.create_batch(2,
                                                              work_group=self.workgroup_one,
                                                              kanban=self.group_one.kanban)
        kanbanentrieswg_two = KanbanEntryFactory.create_batch(6,
                                                              work_group=self.workgroup_two,
                                                              kanban=self.group_two.kanban)

        kanbanentriesg_one = KanbanEntryFactory.create_batch(3,
                                                             kanban=self.group_one.kanban)
        kanbanentriesg_two = KanbanEntryFactory.create_batch(3,
                                                             kanban=self.group_two.kanban,
                                                             assignee=self.group_user_two.user)

        kanbanentriesu_one = KanbanEntryFactory.create_batch(5, kanban=self.group_user_one.user.kanban)
        kanbanentriesu_two = KanbanEntryFactory.create_batch(9, kanban=self.group_user_two.user.kanban)

        response = generate_request(api=UserKanbanEntryListAPI, user=self.group_user_one.user)
        self.assertEqual(response.data['count'], 10)

        response = generate_request(api=UserKanbanEntryListAPI, user=self.group_user_two.user)
        self.assertEqual(response.data['count'], 18)

        response = generate_request(api=UserKanbanEntryListAPI,
                                    user=self.group_user_two.user,
                                    data={'assignee': self.group_user_two.user.id})

        self.assertEqual(response.data['count'], 3)

        response = generate_request(api=UserKanbanEntryListAPI,
                                    user=self.group_user_two.user,
                                    data={'title__icontains': kanbanentriesg_two[0].title})

        self.assertEqual(response.data['count'], 1)

    def test_kanban_change_group(self):
        user = self.group_user_one.user
        GroupUserFactory(group=self.group_two, user=user, is_admin=True)
        entry = KanbanEntryFactory(kanban=self.group_one.kanban,
                                   work_group=self.workgroup_one,
                                   assignee=user)

        response = generate_request(api=GroupKanbanChangeGroupAPI,
                                    user=user,
                                    url_params=dict(group_id=self.group_one.id),
                                    data=dict(entry_id=entry.id, target_group_id=self.group_two.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        entry.refresh_from_db()
        self.assertFalse(entry.active)

        moved = KanbanEntry.objects.get(id=response.data)
        self.assertEqual(moved.kanban_id, self.group_two.kanban.id)
        self.assertEqual((moved.title, moved.lane, moved.priority), (entry.title, entry.lane, entry.priority))
        self.assertEqual(moved.assignee_id, user.id)
        self.assertIsNone(moved.work_group)

    def test_kanban_change_group_drops_non_member_assignee(self):
        user = self.group_user_one.user
        GroupUserFactory(group=self.group_two, user=user, is_admin=True)
        entry = KanbanEntryFactory(kanban=self.group_one.kanban, assignee=user)
        other = GroupUserFactory(group=self.group_one)
        entry.assignee = other.user
        entry.save()

        group_kanban_entry_change_group(fetched_by_id=user.id,
                                        group_id=self.group_one.id,
                                        target_group_id=self.group_two.id,
                                        entry_id=entry.id)

        self.assertIsNone(KanbanEntry.objects.get(kanban=self.group_two.kanban, title=entry.title).assignee)

    def test_kanban_change_group_same_group(self):
        entry = KanbanEntryFactory(kanban=self.group_one.kanban)

        response = generate_request(api=GroupKanbanChangeGroupAPI,
                                    user=self.group_user_one.user,
                                    url_params=dict(group_id=self.group_one.id),
                                    data=dict(entry_id=entry.id, target_group_id=self.group_one.id))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_kanban_change_group_without_target_permission(self):
        user = self.group_user_one.user
        GroupUserFactory(group=self.group_two, user=user, is_admin=False)
        self.group_two.default_permission.create_kanban_task = False
        self.group_two.default_permission.save()
        entry = KanbanEntryFactory(kanban=self.group_one.kanban)

        with self.assertRaises(PermissionDenied):
            group_kanban_entry_change_group(fetched_by_id=user.id,
                                            group_id=self.group_one.id,
                                            target_group_id=self.group_two.id,
                                            entry_id=entry.id)

        entry.refresh_from_db()
        self.assertTrue(entry.active)
        self.assertFalse(KanbanEntry.objects.filter(kanban=self.group_two.kanban).exists())

    def test_kanban_change_group_without_source_permission(self):
        member = GroupUserFactory(group=self.group_one, is_admin=False)
        GroupUserFactory(group=self.group_two, user=member.user, is_admin=True)
        self.group_one.default_permission.delete_kanban_task = False
        self.group_one.default_permission.save()
        entry = KanbanEntryFactory(kanban=self.group_one.kanban)

        with self.assertRaises(PermissionDenied):
            group_kanban_entry_change_group(fetched_by_id=member.user.id,
                                            group_id=self.group_one.id,
                                            target_group_id=self.group_two.id,
                                            entry_id=entry.id)

        entry.refresh_from_db()
        self.assertTrue(entry.active)

    def test_kanban_change_group_without_permission_on_either_group(self):
        member = GroupUserFactory(group=self.group_one, is_admin=False)
        GroupUserFactory(group=self.group_two, user=member.user, is_admin=False)
        self.group_one.default_permission.delete_kanban_task = False
        self.group_one.default_permission.save()
        self.group_two.default_permission.create_kanban_task = False
        self.group_two.default_permission.save()
        entry = KanbanEntryFactory(kanban=self.group_one.kanban)

        response = generate_request(api=GroupKanbanChangeGroupAPI,
                                    user=member.user,
                                    url_params=dict(group_id=self.group_one.id),
                                    data=dict(entry_id=entry.id, target_group_id=self.group_two.id))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        entry.refresh_from_db()
        self.assertTrue(entry.active)
        self.assertFalse(KanbanEntry.objects.filter(kanban=self.group_two.kanban).exists())
