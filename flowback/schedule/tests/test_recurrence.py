"""
Schedule Recurrence Test Suite

This test suite covers:
- Occurrences of repeating events (occurrence, next_occurrence), including daylight saving time
- Timezone validation
- Repeating events (next_start_date, next_end_date, beat task crontab) in the event's timezone
- The event_notify task
"""

import datetime
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django.utils import timezone
from django_celery_beat.models import PeriodicTask
from rest_framework.test import APITestCase

from flowback.notification.models import NotificationObject
from flowback.schedule.models import ScheduleEvent
from flowback.schedule.recurrence import (DAILY, WEEKLY, MONTHLY, YEARLY,
                                          occurrence, occurrence_index, next_occurrence,
                                          validate_timezone_name)
from flowback.schedule.services import schedule_event_update
from flowback.schedule.tasks import event_notify
from flowback.schedule.tests.factories import ScheduleEventFactory

UTC = ZoneInfo('UTC')
STOCKHOLM = ZoneInfo('Europe/Stockholm')


def utc(*args) -> datetime.datetime:
    return datetime.datetime(*args, tzinfo=datetime.timezone.utc)


class OccurrenceTest(SimpleTestCase):
    """Test the occurrences of an event"""

    def test_first_occurrence_is_the_event_itself(self):
        first = utc(2026, 10, 15, 16)

        for frequency in (DAILY, WEEKLY, MONTHLY, YEARLY):
            self.assertEqual(occurrence(first, frequency, 0, STOCKHOLM), first)

    def test_daily_keeps_its_time_when_the_clocks_go_back(self):
        # 18:00 on Oct 15 in Stockholm, the clocks go back on Oct 25
        first = utc(2026, 10, 15, 16)

        self.assertEqual(occurrence(first, DAILY, 9, STOCKHOLM), utc(2026, 10, 24, 16))
        self.assertEqual(occurrence(first, DAILY, 11, STOCKHOLM), utc(2026, 10, 26, 17))

    def test_daily_keeps_its_time_when_the_clocks_go_forward(self):
        # 18:00 on Mar 21 in Stockholm, the clocks go forward on Mar 29
        first = utc(2026, 3, 21, 17)

        self.assertEqual(occurrence(first, DAILY, 7, STOCKHOLM), utc(2026, 3, 28, 17))
        self.assertEqual(occurrence(first, DAILY, 9, STOCKHOLM), utc(2026, 3, 30, 16))

    def test_in_utc_the_time_follows_the_clock_of_the_server_instead(self):
        first = utc(2026, 10, 15, 16)

        self.assertEqual(occurrence(first, DAILY, 11, UTC), utc(2026, 10, 26, 16))

    def test_time_skipped_by_the_clocks_going_forward_is_held_an_hour_later(self):
        # 02:30 doesn't exist on Mar 29 in Stockholm
        first = utc(2026, 3, 28, 1, 30)

        self.assertEqual(occurrence(first, DAILY, 1, STOCKHOLM), utc(2026, 3, 29, 1, 30))  # 03:30 CEST
        self.assertEqual(occurrence(first, DAILY, 2, STOCKHOLM), utc(2026, 3, 30, 0, 30))  # 02:30 CEST

    def test_time_that_happens_twice_is_held_the_first_time(self):
        # 02:30 happens both before and after the clocks go back on Oct 25 in Stockholm
        first = utc(2026, 10, 24, 0, 30)

        self.assertEqual(occurrence(first, DAILY, 1, STOCKHOLM), utc(2026, 10, 25, 0, 30))  # 02:30 CEST

    def test_weekly_keeps_its_weekday_and_time(self):
        # Wednesday 18:00 in Stockholm
        first = utc(2026, 10, 14, 16)

        self.assertEqual(occurrence(first, WEEKLY, 2, STOCKHOLM), utc(2026, 10, 28, 17))
        self.assertEqual(occurrence(first, WEEKLY, 2, STOCKHOLM).astimezone(STOCKHOLM).weekday(), 2)

    def test_monthly_skips_months_without_the_day(self):
        first = utc(2026, 1, 31, 12)

        self.assertEqual(occurrence(first, MONTHLY, 1, STOCKHOLM), None)  # February
        self.assertEqual(occurrence(first, MONTHLY, 2, STOCKHOLM), utc(2026, 3, 31, 11))
        self.assertEqual(occurrence(first, MONTHLY, 3, STOCKHOLM), None)  # April
        self.assertEqual(occurrence(first, MONTHLY, 4, STOCKHOLM), utc(2026, 5, 31, 11))

    def test_monthly_goes_into_the_next_year(self):
        first = utc(2026, 11, 15, 12)

        self.assertEqual(occurrence(first, MONTHLY, 3, STOCKHOLM), utc(2027, 2, 15, 12))

    def test_yearly_on_leap_day_skips_years_that_are_not_leap_years(self):
        first = utc(2024, 2, 29, 12)

        for index in (1, 2, 3):
            self.assertEqual(occurrence(first, YEARLY, index, STOCKHOLM), None)
        self.assertEqual(occurrence(first, YEARLY, 4, STOCKHOLM), utc(2028, 2, 29, 12))

    def test_unknown_frequency(self):
        with self.assertRaises(ValueError):
            occurrence(utc(2026, 10, 15), 5, 1, STOCKHOLM)


class NextOccurrenceTest(SimpleTestCase):
    """Test finding the next occurrence of an event"""

    def test_before_the_first_occurrence(self):
        first = utc(2026, 10, 15, 16)

        self.assertEqual(next_occurrence(first, DAILY, STOCKHOLM, after=utc(2026, 10, 1)), first)

    def test_is_after_the_given_time(self):
        first = utc(2026, 10, 15, 16)
        occurrence_time = utc(2026, 11, 4, 17)

        self.assertEqual(next_occurrence(first, DAILY, STOCKHOLM, after=utc(2026, 11, 3, 20)), occurrence_time)
        self.assertEqual(next_occurrence(first, DAILY, STOCKHOLM, after=occurrence_time), utc(2026, 11, 5, 17))

    def test_many_years_after_the_first_occurrence(self):
        first = utc(2026, 10, 15, 16)
        after = utc(2046, 6, 1, 12)

        for frequency in (DAILY, WEEKLY, MONTHLY, YEARLY):
            result = next_occurrence(first, frequency, STOCKHOLM, after=after)
            self.assertGreater(result, after)
            self.assertEqual(result.astimezone(STOCKHOLM).time(), datetime.time(18))

        self.assertEqual(next_occurrence(first, DAILY, STOCKHOLM, after=after), utc(2046, 6, 1, 16))

    def test_skips_months_and_years_without_the_day(self):
        self.assertEqual(next_occurrence(utc(2026, 1, 31, 12), MONTHLY, STOCKHOLM, after=utc(2026, 2, 1)),
                         utc(2026, 3, 31, 11))
        self.assertEqual(next_occurrence(utc(2024, 2, 29, 12), YEARLY, STOCKHOLM, after=utc(2024, 3, 1)),
                         utc(2028, 2, 29, 12))

    def test_stops_at_the_last_occurrence(self):
        first = utc(2026, 10, 15, 16)
        last = utc(2026, 11, 3, 17)

        self.assertEqual(next_occurrence(first, DAILY, STOCKHOLM, after=utc(2026, 11, 2, 20), last=last), last)
        self.assertIsNone(next_occurrence(first, DAILY, STOCKHOLM, after=utc(2026, 11, 3, 20), last=last))


class OccurrenceIndexTest(SimpleTestCase):
    """Test finding which occurrence an event holds at a time"""

    def test_first_occurrence_is_index_zero(self):
        first = utc(2026, 10, 15, 16)

        for frequency in (DAILY, WEEKLY, MONTHLY, YEARLY):
            self.assertEqual(occurrence_index(first, frequency, STOCKHOLM, first), 0)

    def test_is_the_index_of_the_occurrence_at_that_time(self):
        first = utc(2026, 10, 15, 16)

        for frequency in (DAILY, WEEKLY, MONTHLY, YEARLY):
            for index in (1, 5, 30):
                at = occurrence(first, frequency, index, STOCKHOLM)
                if at is not None:
                    self.assertEqual(occurrence_index(first, frequency, STOCKHOLM, at), index)

    def test_follows_the_clocks_of_the_timezone(self):
        # 18:00 in Stockholm on Oct 15, then 18:00 is 17:00 in UTC when the clocks go back on Oct 25
        first = utc(2026, 10, 15, 16)

        self.assertEqual(occurrence_index(first, DAILY, STOCKHOLM, utc(2026, 10, 26, 17)), 11)
        self.assertIsNone(occurrence_index(first, DAILY, STOCKHOLM, utc(2026, 10, 26, 16)))

    def test_a_time_to_the_millisecond_is_the_same_time(self):
        first = utc(2026, 10, 15, 16).replace(microsecond=790514)

        for at in (first.replace(microsecond=790000), first.replace(microsecond=791000)):
            self.assertEqual(occurrence_index(first, DAILY, UTC, at), 0)

        self.assertIsNone(occurrence_index(first, DAILY, UTC, first.replace(microsecond=792000)))

    def test_is_none_between_occurrences(self):
        first = utc(2026, 10, 15, 16)

        self.assertIsNone(occurrence_index(first, WEEKLY, UTC, utc(2026, 10, 16, 16)))
        self.assertIsNone(occurrence_index(first, WEEKLY, UTC, utc(2026, 10, 22, 17)))

    def test_is_none_before_the_first_occurrence(self):
        self.assertIsNone(occurrence_index(utc(2026, 10, 15, 16), DAILY, UTC, utc(2026, 10, 14, 16)))

    def test_is_none_in_a_month_without_the_day(self):
        self.assertIsNone(occurrence_index(utc(2026, 1, 31, 12), MONTHLY, UTC, utc(2026, 2, 28, 12)))

    def test_is_none_after_the_last_occurrence(self):
        first = utc(2026, 10, 15, 16)

        self.assertEqual(occurrence_index(first, DAILY, UTC, utc(2026, 10, 17, 16), last=utc(2026, 10, 17, 16)), 2)
        self.assertIsNone(occurrence_index(first, DAILY, UTC, utc(2026, 10, 18, 16), last=utc(2026, 10, 17, 16)))


class ValidateTimezoneTest(SimpleTestCase):
    """Test timezone validation"""

    def test_iana_names_are_valid(self):
        for name in ('UTC', 'Europe/Stockholm', 'America/Argentina/Buenos_Aires'):
            validate_timezone_name(name)

    def test_other_names_are_invalid(self):
        for name in ('', 'Stockholm', 'Europe', '../etc/passwd', 'CEST'):
            with self.assertRaises(ValidationError, msg=name):
                validate_timezone_name(name)


class ScheduleEventRecurrenceTest(APITestCase):
    """Test repeating events in the event's timezone"""

    def create_event(self, **kwargs) -> ScheduleEvent:
        # 18:00 to 19:00 on Oct 15 in Stockholm, the clocks go back on Oct 25
        return ScheduleEventFactory.create(start_date=utc(2026, 10, 15, 16),
                                           end_date=utc(2026, 10, 15, 17),
                                           repeat_frequency=ScheduleEvent.Frequency.DAILY,
                                           **kwargs)

    def test_timezone_is_utc_by_default(self):
        self.assertEqual(self.create_event().timezone, 'UTC')

    def test_next_dates_follow_the_event_timezone(self):
        event = self.create_event(timezone='Europe/Stockholm')

        with mock.patch('django.utils.timezone.now', return_value=utc(2026, 10, 25, 12)):
            self.assertEqual(event.next_start_date, utc(2026, 10, 25, 17))
            self.assertEqual(event.next_end_date, utc(2026, 10, 25, 18))

    def test_next_dates_in_utc_do_not_follow_the_clocks(self):
        event = self.create_event()

        with mock.patch('django.utils.timezone.now', return_value=utc(2026, 10, 25, 12)):
            self.assertEqual(event.next_start_date, utc(2026, 10, 25, 16))
            self.assertEqual(event.next_end_date, utc(2026, 10, 25, 17))

    def test_next_dates_before_the_event_has_started(self):
        event = self.create_event(timezone='Europe/Stockholm')

        with mock.patch('django.utils.timezone.now', return_value=utc(2026, 10, 1)):
            self.assertEqual(event.next_start_date, event.start_date)
            self.assertEqual(event.next_end_date, event.end_date)

    def test_event_that_does_not_repeat_has_no_next_dates_when_over(self):
        event = ScheduleEventFactory.create(start_date=utc(2026, 10, 15, 16), end_date=utc(2026, 10, 15, 17))

        with mock.patch('django.utils.timezone.now', return_value=utc(2026, 10, 25, 12)):
            self.assertIsNone(event.next_start_date)
            self.assertIsNone(event.next_end_date)

    def test_next_dates_stop_after_the_repeat_end_date(self):
        event = self.create_event(timezone='Europe/Stockholm',
                                  repeat_frequency_end_date=utc(2026, 10, 20, 16))

        with mock.patch('django.utils.timezone.now', return_value=utc(2026, 10, 20, 16, 30)):
            self.assertIsNone(event.next_start_date)
            # The last occurrence starts on the repeat end date and ends after it
            self.assertEqual(event.next_end_date, utc(2026, 10, 20, 17))

        with mock.patch('django.utils.timezone.now', return_value=utc(2026, 10, 20, 17, 30)):
            self.assertIsNone(event.next_start_date)
            self.assertIsNone(event.next_end_date)

    def test_beat_task_runs_in_the_event_timezone(self):
        event = self.create_event(timezone='Europe/Stockholm')

        crontab = PeriodicTask.objects.get(name=f"schedule_event_{event.id}").crontab
        self.assertEqual(crontab.timezone, STOCKHOLM)
        self.assertEqual((crontab.hour, crontab.minute), ('19', '0'))

    def test_changing_the_timezone_updates_the_beat_task(self):
        event = self.create_event(timezone='Europe/Stockholm')

        schedule_event_update(event_id=event.id, timezone='UTC')

        crontab = PeriodicTask.objects.get(name=f"schedule_event_{event.id}").crontab
        self.assertEqual(crontab.timezone, UTC)
        self.assertEqual((crontab.hour, crontab.minute), ('17', '0'))

    def test_changing_the_timezone_regenerates_the_notifications(self):
        event = self.create_event(timezone='Europe/Stockholm')

        with mock.patch('django.utils.timezone.now', return_value=utc(2026, 10, 25, 12)):
            schedule_event_update(event_id=event.id, timezone='UTC')

            timestamps = event.notification_channel.notificationobject_set.filter(
                timestamp__gte=timezone.now()).values_list('timestamp', flat=True)
            self.assertCountEqual(timestamps, [utc(2026, 10, 25, 16), utc(2026, 10, 25, 17)])


class EventNotifyTaskTest(APITestCase):
    """Test the beat task of repeating events"""

    def test_notifies_the_next_occurrence_with_a_repeat_end_date(self):
        event = ScheduleEventFactory.create(start_date=utc(2026, 10, 15, 16),
                                            end_date=utc(2026, 10, 15, 17),
                                            repeat_frequency=ScheduleEvent.Frequency.DAILY,
                                            repeat_frequency_end_date=utc(2026, 11, 1, 16),
                                            timezone='Europe/Stockholm')

        with mock.patch('django.utils.timezone.now', return_value=utc(2026, 10, 25, 18)):
            event_notify(event.id)

            timestamps = event.notification_channel.notificationobject_set.filter(
                timestamp__gte=timezone.now()).values_list('timestamp', flat=True)
            self.assertCountEqual(timestamps, [utc(2026, 10, 26, 17), utc(2026, 10, 26, 18)])

    def test_leaves_no_notifications_once_the_event_has_stopped_repeating(self):
        event = ScheduleEventFactory.create(start_date=utc(2026, 10, 15, 16),
                                            end_date=utc(2026, 10, 15, 17),
                                            repeat_frequency=ScheduleEvent.Frequency.DAILY,
                                            repeat_frequency_end_date=utc(2026, 10, 20, 16))

        with mock.patch('django.utils.timezone.now', return_value=utc(2026, 10, 20, 18)):
            event_notify(event.id)

            self.assertFalse(event.notification_channel.notificationobject_set.filter(
                timestamp__gte=timezone.now()).exists())

    def test_stops_the_task_of_a_removed_event(self):
        event = ScheduleEventFactory.create(start_date=utc(2026, 10, 15, 16),
                                            end_date=utc(2026, 10, 15, 17),
                                            repeat_frequency=ScheduleEvent.Frequency.DAILY)
        event_id = event.id
        self.assertTrue(PeriodicTask.objects.filter(name=f"schedule_event_{event_id}").exists())

        ScheduleEvent.objects.filter(id=event_id).delete()
        event_notify(event_id)

        self.assertFalse(PeriodicTask.objects.filter(name=f"schedule_event_{event_id}").exists())
