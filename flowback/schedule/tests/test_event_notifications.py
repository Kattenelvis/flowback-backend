"""
Schedule Event Notification Test Suite

This test suite covers:
- The notifications and reminders a subscriber gets for an event, repeating or not
- Subscribing to a single occurrence of a repeating event
- Subscribing after the notifications of the next occurrence were made
- Reminders being shown ahead of the event
"""

from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from freezegun import freeze_time
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from flowback.common.tests import generate_request
from flowback.group.tests.factories import GroupFactory
from flowback.notification.models import Notification, NotificationObject
from flowback.notification.selectors import notification_list
from flowback.schedule.models import ScheduleEventSubscription
from flowback.schedule.recurrence import WEEKLY
from flowback.schedule.selectors import schedule_event_list
from flowback.schedule.tasks import event_notify
from flowback.schedule.services import schedule_event_subscribe, schedule_event_unsubscribe
from flowback.schedule.tests.factories import ScheduleTagFactory, ScheduleTagSubscriptionFactory
from flowback.schedule.views import ScheduleEventListAPI, ScheduleEventSubscribeAPI
from flowback.user.tests.factories import UserFactory

class EventNotificationTestBase(APITestCase):
    def setUp(self):
        self.user = UserFactory.create()
        self.group = GroupFactory.create()
        self.schedule = self.group.schedule
        self.schedule.add_user(self.user)

    def create_event(self, start, **kwargs):
        return self.schedule.create_event(title='Meeting',
                                          start_date=start,
                                          end_date=start + timedelta(hours=1),
                                          created_by=self.group,
                                          **kwargs)

    def subscribe(self, event, **kwargs):
        schedule_event_subscribe(user=self.user, schedule_id=self.schedule.id, event_ids=[event.id], **kwargs)

    def notifications(self):
        return sorted(Notification.objects.filter(user=self.user).values_list('notification_object__tag', 'reminder'))

    def channel_subscribers(self, event):
        return event.notification_channel.notificationsubscription_set.filter(user=self.user).count()


class EventNotificationTest(EventNotificationTestBase):
    def test_event_that_does_not_repeat_has_notifications(self):
        """A one-off event is notified when it starts and ends, not only the repeating ones"""
        start = timezone.now() + timedelta(hours=2)
        event = self.create_event(start)

        objects = NotificationObject.objects.filter(channel=event.notification_channel)
        self.assertEqual(sorted(objects.values_list('tag', flat=True)), ['end', 'start'])

        self.subscribe(event)
        self.assertEqual(self.notifications(), [('end', 0), ('start', 0)])

    def test_event_in_the_past_has_no_notifications(self):
        event = self.create_event(timezone.now() - timedelta(days=2))

        self.assertFalse(NotificationObject.objects.filter(channel=event.notification_channel).exists())

    def test_subscribing_after_the_next_occurrence_was_made_still_notifies(self):
        """The notifications of the next occurrence are made ahead of time, subscribers still get them"""
        event = self.create_event(timezone.now() + timedelta(hours=2), repeat_frequency=WEEKLY)

        self.subscribe(event, reminders=[3600])

        self.assertEqual(self.notifications(), [('end', 0), ('start', 0), ('start', 3600)])

    def test_reminder_that_should_have_been_shown_is_not_made(self):
        event = self.create_event(timezone.now() + timedelta(minutes=30))

        self.subscribe(event, reminders=[3600, 600])

        self.assertEqual(self.notifications(), [('end', 0), ('start', 0), ('start', 600)])

    def test_subscribing_again_changes_the_reminders(self):
        event = self.create_event(timezone.now() + timedelta(hours=5))

        self.subscribe(event, reminders=[3600])
        self.subscribe(event, reminders=[7200])

        self.assertEqual(self.notifications(), [('end', 0), ('start', 0), ('start', 7200)])
        self.assertEqual(ScheduleEventSubscription.objects.get(event=event).reminders, [7200])

    def test_unsubscribing_removes_the_notifications_to_come(self):
        event = self.create_event(timezone.now() + timedelta(hours=5), repeat_frequency=WEEKLY)
        self.subscribe(event, reminders=[3600])

        schedule_event_unsubscribe(user=self.user, schedule_id=self.schedule.id, event_ids=[event.id])

        self.assertEqual(self.notifications(), [])
        self.assertEqual(self.channel_subscribers(event), 0)

    def test_unsubscribing_keeps_the_reminders_already_shown(self):
        start = timezone.now() + timedelta(hours=5)
        event = self.create_event(start)
        self.subscribe(event, reminders=[3600])

        with freeze_time(start - timedelta(minutes=30)):
            schedule_event_unsubscribe(user=self.user, schedule_id=self.schedule.id, event_ids=[event.id])

        self.assertEqual(self.notifications(), [('start', 3600)])

    def test_notification_list_shows_reminders_ahead_of_the_event(self):
        start = timezone.now() + timedelta(hours=2)
        event = self.create_event(start)
        self.subscribe(event, reminders=[3600])
        self.assertEqual(notification_list(user=self.user).count(), 0)

        with freeze_time(start - timedelta(minutes=30)):
            shown = notification_list(user=self.user)
            self.assertEqual(list(shown.values_list('notification_object__tag', 'reminder')), [('start', 3600)])

        with freeze_time(start + timedelta(minutes=1)):
            self.assertEqual(notification_list(user=self.user).count(), 2)

    def test_notification_list_orders_reminders_by_when_they_are_shown(self):
        event = self.create_event(timezone.now() + timedelta(hours=3))
        self.subscribe(event, reminders=[7200, 3600])

        with freeze_time(timezone.now() + timedelta(hours=4)):
            ordered = list(notification_list(user=self.user,
                                             filters=dict(order_by='timestamp_asc')
                                             ).values_list('notification_object__tag', 'reminder'))

        self.assertEqual(ordered, [('start', 7200), ('start', 3600), ('start', 0), ('end', 0)])

    def test_tag_subscription_does_not_change_what_the_user_chose(self):
        tag = ScheduleTagFactory.create(schedule=self.schedule, name='meetings')
        event = self.create_event(timezone.now() + timedelta(days=1), repeat_frequency=WEEKLY, tag='meetings')
        occurrence = event.start_date
        self.subscribe(event, occurrence_start=occurrence, reminders=[60])

        ScheduleTagSubscriptionFactory.create(schedule_user=self.schedule.scheduleuser_set.get(user=self.user),
                                              schedule_tag=tag,
                                              reminders=[300])

        subscription = ScheduleEventSubscription.objects.get(event=event)
        self.assertEqual(subscription.occurrence_start, occurrence)
        self.assertEqual(subscription.reminders, [60])
        self.assertTrue(subscription.locked)


class EventOccurrenceSubscriptionTest(EventNotificationTestBase):
    def setUp(self):
        super().setUp()
        # Held weekly, with the next occurrence tomorrow
        self.start = timezone.now() - timedelta(days=6) + timedelta(hours=1)
        self.event = self.create_event(self.start, repeat_frequency=WEEKLY)
        self.next = self.event.next_start_date
        self.after_next = self.next + timedelta(weeks=1)

    def test_whole_series_is_followed_by_default(self):
        self.subscribe(self.event)

        self.assertEqual(ScheduleEventSubscription.objects.get(event=self.event).occurrence_start, None)
        self.assertEqual(self.channel_subscribers(self.event), 1)

    def test_single_occurrence_is_notified_without_following_the_series(self):
        self.subscribe(self.event, occurrence_start=self.next, reminders=[600])

        self.assertEqual(self.channel_subscribers(self.event), 0)
        self.assertEqual(self.notifications(), [('end', 0), ('start', 0), ('start', 600)])

    def test_single_occurrence_that_is_not_next_waits_for_its_notifications(self):
        self.subscribe(self.event, occurrence_start=self.after_next)
        self.assertEqual(self.notifications(), [])

        # The notifications of the occurrence after are made when the next one has ended
        with freeze_time(self.next + timedelta(hours=2)):
            self.event.regenerate_notifications()
            self.assertEqual(self.notifications(), [('end', 0), ('start', 0)])
            self.assertEqual(Notification.objects.get(user=self.user, notification_object__tag='start')
                             .notification_object.timestamp, self.after_next)

    def test_single_occurrence_is_not_notified_about_the_ones_after(self):
        self.subscribe(self.event, occurrence_start=self.next)

        with freeze_time(self.next + timedelta(hours=2)):
            self.event.regenerate_notifications()

        timestamps = set(Notification.objects.filter(user=self.user)
                         .values_list('notification_object__timestamp', flat=True))
        self.assertNotIn(self.after_next, timestamps)

    def test_series_follower_is_notified_about_every_occurrence(self):
        self.subscribe(self.event)

        with freeze_time(self.next + timedelta(hours=2)):
            self.event.regenerate_notifications()

        self.assertIn(self.after_next, set(Notification.objects.filter(user=self.user)
                                           .values_list('notification_object__timestamp', flat=True)))

    def test_single_occurrence_follower_is_done_once_it_has_been_held(self):
        series_follower = UserFactory.create()
        self.schedule.add_user(series_follower)
        schedule_event_subscribe(user=series_follower, schedule_id=self.schedule.id, event_ids=[self.event.id])
        self.subscribe(self.event, occurrence_start=self.next)

        with freeze_time(self.next + timedelta(hours=2)):
            event_notify(self.event.id)

        self.assertEqual(list(ScheduleEventSubscription.objects.values_list('schedule_user__user', flat=True)),
                         [series_follower.id])

    def test_switching_between_single_occurrence_and_series(self):
        self.subscribe(self.event)
        self.subscribe(self.event, occurrence_start=self.next)

        self.assertEqual(ScheduleEventSubscription.objects.filter(event=self.event).count(), 1)
        self.assertEqual(self.channel_subscribers(self.event), 0)
        self.assertEqual(self.notifications(), [('end', 0), ('start', 0)])

        self.subscribe(self.event)

        self.assertEqual(ScheduleEventSubscription.objects.get(event=self.event).occurrence_start, None)
        self.assertEqual(self.channel_subscribers(self.event), 1)
        self.assertEqual(self.notifications(), [('end', 0), ('start', 0)])

    def test_switching_to_another_occurrence_replaces_the_notifications(self):
        self.subscribe(self.event, occurrence_start=self.next)
        self.subscribe(self.event, occurrence_start=self.after_next)

        self.assertEqual(self.notifications(), [])

    def test_unsubscribing_a_single_occurrence_removes_its_notifications(self):
        self.subscribe(self.event, occurrence_start=self.next, reminders=[600])

        schedule_event_unsubscribe(user=self.user, schedule_id=self.schedule.id, event_ids=[self.event.id])

        self.assertEqual(self.notifications(), [])

    def test_occurrence_is_found_by_a_time_to_the_millisecond(self):
        """Clients know times to the millisecond, the events are made to the microsecond"""
        self.event.start_date = self.event.start_date.replace(microsecond=790514)
        self.event.end_date = self.event.start_date + timedelta(hours=1)
        self.event.save()
        self.event.regenerate_notifications()
        next_start = self.event.next_start_date
        to_the_millisecond = next_start.replace(microsecond=790000)

        self.subscribe(self.event, occurrence_start=to_the_millisecond)

        self.assertEqual(ScheduleEventSubscription.objects.get(event=self.event).occurrence_start, next_start)
        self.assertEqual(self.notifications(), [('end', 0), ('start', 0)])

    def test_time_that_is_not_an_occurrence_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.subscribe(self.event, occurrence_start=self.next + timedelta(hours=1))

        self.assertFalse(ScheduleEventSubscription.objects.exists())

    def test_occurrence_that_has_ended_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.subscribe(self.event, occurrence_start=self.start)

    def test_occurrence_after_the_repeating_stops_is_rejected(self):
        self.event.repeat_frequency_end_date = self.next
        self.event.save(update_fields=['repeat_frequency_end_date'])

        self.subscribe(self.event, occurrence_start=self.next)
        with self.assertRaises(ValidationError):
            self.subscribe(self.event, occurrence_start=self.after_next)

    def test_event_that_does_not_repeat_only_has_its_own_start(self):
        one_off = self.create_event(timezone.now() + timedelta(days=3))

        self.subscribe(one_off, occurrence_start=one_off.start_date)
        with self.assertRaises(ValidationError):
            self.subscribe(one_off, occurrence_start=one_off.start_date + timedelta(weeks=1))


class EventSubscriptionAPITest(EventNotificationTestBase):
    def test_subscribe_to_an_occurrence_and_list_it(self):
        start = timezone.now() + timedelta(days=1)
        event = self.create_event(start, repeat_frequency=WEEKLY)

        response = generate_request(api=ScheduleEventSubscribeAPI,
                                    data={'event_ids': str(event.id), 'occurrence_start': start.isoformat()},
                                    url_params={'schedule_id': self.schedule.id},
                                    user=self.user)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        listed = generate_request(api=ScheduleEventListAPI, data={'ids': str(event.id)}, user=self.user)
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        result = listed.data['results'][0]
        self.assertTrue(result['subscribed'])
        self.assertEqual(parse_datetime(result['subscribed_occurrence']), start)

    def test_subscribe_to_the_series_is_listed_without_an_occurrence(self):
        event = self.create_event(timezone.now() + timedelta(days=1), repeat_frequency=WEEKLY)
        self.subscribe(event)

        result = schedule_event_list(user=self.user, filters={}).get(id=event.id)

        self.assertTrue(result.subscribed)
        self.assertIsNone(result.subscribed_occurrence)

    def test_occurrence_that_does_not_exist_is_a_bad_request(self):
        start = timezone.now() + timedelta(days=1)
        event = self.create_event(start, repeat_frequency=WEEKLY)

        response = generate_request(api=ScheduleEventSubscribeAPI,
                                    data={'event_ids': str(event.id),
                                          'occurrence_start': (start + timedelta(days=1)).isoformat()},
                                    url_params={'schedule_id': self.schedule.id},
                                    user=self.user)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
