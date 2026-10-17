import datetime
import json
from zoneinfo import ZoneInfo

import pgtrigger
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import ArrayField
from django.db import models, transaction
from django.db.models import DurationField, ExpressionWrapper, F, Q
from django.db.models.signals import post_save, pre_delete
from django.utils import timezone
from django_celery_beat.models import PeriodicTask, CrontabSchedule
from rest_framework.exceptions import ValidationError

from flowback.common.models import BaseModel
from flowback.common.validators import FieldNotBlankValidator
from flowback.schedule import recurrence
from flowback.schedule.recurrence import validate_timezone_name
from django.utils.translation import gettext_lazy as _

from flowback.notification.models import NotifiableModel, NotificationObject, Notification


class Schedule(BaseModel):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    created_by = GenericForeignKey('content_type', 'object_id')

    default_tag = models.ForeignKey('schedule.ScheduleTag',
                                    on_delete=models.CASCADE,
                                    null=True,
                                    blank=True,
                                    related_name='default_tag')

    active = models.BooleanField(default=True)

    # Create Event
    def create_event(self, *,
                     title: str,
                     description: str = None,
                     start_date: datetime,
                     end_date: datetime = None,
                     created_by=None,
                     tag: str = None,
                     assignees: list[int] = None,
                     meeting_link: str = None,
                     repeat_frequency: int = None,
                     repeat_frequency_end_date: datetime = None,
                     timezone: str = 'UTC'):
        if not tag and not self.default_tag:
            raise ValidationError("Schedule must either have a tag or a default tag.")

        tag, created = ScheduleTag.objects.get_or_create(schedule=self, name=tag if tag else self.default_tag.name)
        event = ScheduleEvent(title=title,
                              description=description,
                              start_date=start_date,
                              end_date=end_date,
                              schedule=self,
                              created_by=created_by,
                              tag=tag or self.default_tag,
                              meeting_link=meeting_link,
                              repeat_frequency=repeat_frequency,
                              repeat_frequency_end_date=repeat_frequency_end_date,
                              timezone=timezone)

        if assignees:
            event.assignees.add(*assignees)

        event.full_clean()
        event.save()

        return event

    def add_user(self, user, raise_exception: bool = False):
        """
        Add user to schedule
        :param user: User to be added
        :param raise_exception: Raises VaildationError if user is subscribed
        :return: ScheduleUser object
        """
        with transaction.atomic():
            if not ScheduleUser.objects.filter(user=user, schedule=self).exists():
                schedule_user = ScheduleUser(user=user, schedule=self)
                schedule_user.full_clean()
                schedule_user.save()

                return schedule_user

            elif raise_exception:
                raise ValidationError("User is already added to this schedule.")

        return None

    def remove_user(self, user, raise_exception: bool = False) -> None:
        """
        Remove user from schedule
        :param user: User to be removed
        :param raise_exception: Raises VaildationError if user is unsubscribed
        :return: None
        """
        with transaction.atomic():
            schedule_user = ScheduleUser.objects.filter(user=user, schedule=self).first()
            if schedule_user:
                schedule_user.delete()
            elif raise_exception:
                raise ValidationError("User is not added to this schedule.")

            return None

    def subscribe_new_tags(self, user, reminders: list[int] = None):
        """
        Subscribes to new tags
        :param user: User to subscribe
        :param reminders: A list of reminders (in seconds before the event begins)
        :return: ScheduleUser object
        """
        with transaction.atomic():
            schedule_user = ScheduleUser.objects.get(user=user, schedule=self)
            schedule_user.subscribe_to_new_notification_tags = True
            schedule_user.reminders = reminders
            schedule_user.save()
            return schedule_user

    def unsubscribe_new_tags(self, user):
        """
        Unsubscribes from new tags
        :param user: User to subscribe
        :return: ScheduleUser object
        """
        with transaction.atomic():
            schedule_user = ScheduleUser.objects.get(user=user, schedule=self)
            schedule_user.subscribe_to_new_notification_tags = False
            schedule_user.reminders = None
            schedule_user.save()
            return schedule_user

    def subscribe_tags(self, user, tag_ids: list, reminders: list[int] = None):
        """
        Subscribe to a schedule.
        :param user: A user object
        :param tag_ids: A list of tag id's
        :param reminders: A list of reminders (in seconds before the event begins)
        :return: ScheduleUser object
        """
        with transaction.atomic():
            schedule_user = ScheduleUser.objects.get(user=user, schedule=self)
            tags = ScheduleTag.objects.filter(schedule=self, id__in=tag_ids)
            for tag in tags:
                ScheduleTagSubscription.objects.update_or_create(schedule_user=schedule_user,
                                                                 schedule_tag=tag,
                                                                 defaults=dict(reminders=reminders))

    def unsubscribe_tags(self, user, tag_ids: list):
        """
        Unsubscribes from schedule tags.
        :param user: A user object
        :param tag_ids: A list of tag id's, leave empty to unsubscribe from all tags
        :return: ScheduleUser object
        """
        filters = {} if not tag_ids else dict(schedule_tag__id__in=tag_ids)

        with transaction.atomic():
            schedule_user = ScheduleUser.objects.get(user=user, schedule=self)
            tags = ScheduleTagSubscription.objects.filter(schedule_user=schedule_user,
                                                          **filters)

            if not tags.exists():
                raise ValidationError("User is not subscribed to any of the tags.")

            tags.delete()

    def subscribe_events(self, user, event_ids: list[int], user_tags: list[str], reminders: list[int], locked: bool,
                         occurrence_start: datetime.datetime = None):
        """
        Subscribe a user to a specified event with optional user tags and locked status.

        :param user: The user object who is subscribing to the event.
        :param event_id: ID of the event to subscribe to.
        :param user_tags: A list of user-defined tags.
        :param reminders: A list of reminders (in seconds before the event begins)
        :param locked: A boolean indicating whether the event subscription is locked
         (that is, not affected by tag subscribe/unsubscribe).
        :param occurrence_start: Start of the one occurrence of a repeating event to follow, leave empty to follow all.
        :return: ScheduleEventUserData object
        """
        with transaction.atomic():
            events = ScheduleEvent.objects.filter(id__in=event_ids, schedule=self)

            if len(event_ids) > events.count():
                raise ValidationError("One or more events does not exist.")

            for event in events:
                event.event_subscribe(user, user_tags, locked, reminders, occurrence_start)

    def unsubscribe_events(self, user, event_ids: list[int]) -> None:
        """
        Unsubscribes a user from a specified event.

        :param user: The user object who is unsubscribing from the event.
        :param event_id: ID of the event to unsubscribe from.
        :return: None
        """
        with transaction.atomic():
            events = ScheduleEvent.objects.filter(id__in=event_ids, schedule=self)
            for event in events:
                event.event_unsubscribe(user)

    @classmethod
    def post_save(cls, instance, created, *args, **kwargs):
        if not created:
            return

        default_tag = ScheduleTag.objects.create(schedule=instance, name='default')
        instance.default_tag = default_tag
        instance.save()


post_save.connect(Schedule.post_save, Schedule)


class ScheduleTag(BaseModel, NotifiableModel):
    schedule = models.ForeignKey(Schedule, on_delete=models.CASCADE)
    name = models.CharField(max_length=100, validators=[FieldNotBlankValidator])

    class Meta:
        constraints = [models.UniqueConstraint(fields=['schedule', 'name'], name='scheduleuniquenameconstraint')]

    @classmethod
    def post_save(cls, instance, created, *args, **kwargs):
        if not created:
            return

        subscriptions = ScheduleUser.objects.filter(schedule=instance.schedule,
                                                    subscribe_to_new_notification_tags=True)

        for sub in subscriptions:
            ScheduleTagSubscription.objects.get_or_create(schedule_subscription=sub,
                                                          schedule_tag=instance)


post_save.connect(ScheduleTag.post_save, ScheduleTag)


class ScheduleEvent(BaseModel, NotifiableModel):
    class Frequency(models.IntegerChoices):
        DAILY = recurrence.DAILY, _("Daily")
        WEEKLY = recurrence.WEEKLY, _("Weekly")
        MONTHLY = recurrence.MONTHLY, _("Monthly")  # If event start_date day is 29 or higher, skip months that has these dates
        YEARLY = recurrence.YEARLY, _("Yearly")

    schedule = models.ForeignKey(Schedule, on_delete=models.CASCADE)
    title = models.TextField(validators=[FieldNotBlankValidator])
    description = models.TextField(null=True, blank=True, validators=[FieldNotBlankValidator])
    start_date = models.DateTimeField()
    end_date = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)
    tag = models.ForeignKey(ScheduleTag, on_delete=models.CASCADE)

    # Making assignees to User serves no purpose but to complicate queries
    assignees = models.ManyToManyField('group.GroupUser')
    meeting_link = models.URLField(null=True, blank=True)

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    created_by = GenericForeignKey('content_type', 'object_id')

    repeat_frequency = models.IntegerField(null=True, blank=True, choices=Frequency.choices)
    repeat_frequency_end_date = models.DateTimeField(null=True, blank=True)

    # Repeating events keep their wall-clock time in this timezone (IANA name), also when the clocks change
    timezone = models.CharField(max_length=64, default='UTC', validators=[validate_timezone_name])

    NOTIFICATION_DATA_FIELDS = (('id', int),
                                ('title', str),
                                ('description', str),
                                ('origin_name', str, 'Related model name for the event'),
                                ('origin_id', int, 'Related model ID for the event'),
                                ('schedule_origin_name', str, 'Related model name for the schedule'),
                                ('schedule_origin_id', int, 'Related model ID for the schedule'),
                                ('start_date', datetime),
                                ('end_date', datetime))

    def clean(self, *args, **kwargs):
        if self.end_date and self.start_date > self.end_date:
            raise ValidationError('Start date is greater than end date')

    @property
    def notification_data(self):
        return dict(id=self.id,
                    title=self.title,
                    description=self.description,
                    origin_name=self.content_type.model,
                    origin_id=self.object_id,
                    schedule_origin_name=self.schedule.content_type.model,
                    schedule_origin_id=self.schedule.object_id,
                    start_date=self.start_date.strftime('%Y-%m-%d %H:%M:%S'),
                    end_date=self.end_date.strftime('%Y-%m-%d %H:%M:%S') if self.end_date else None)

    def notify_start(self, action: NotificationObject.Action, timestamp: datetime.datetime, message: str):
        data = locals()
        data.pop('self')

        return self.notification_channel.notify(**data)

    def notify_end(self, action: NotificationObject.Action, timestamp: datetime.datetime, message: str):
        data = locals()
        data.pop('self')

        return self.notification_channel.notify(**data)

    @property
    def zone_info(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def _next_occurrence(self, first: datetime.datetime, last: datetime.datetime | None):
        return recurrence.next_occurrence(first=first,
                                          frequency=self.repeat_frequency,
                                          tz=self.zone_info,
                                          after=timezone.now(),
                                          last=last)

    @property
    def is_live(self) -> bool:
        """Returns true if the event has yet to begin, already begun or has occurrences to come, false otherwise."""
        if not self.active:
            return False

        if not self.end_date or self.end_date >= timezone.now():
            return True

        # end_date is where the first occurrence of a repeating event ends
        return bool(self.repeat_frequency) and self.next_end_date is not None

    @property
    def next_start_date(self) -> datetime.datetime | None:
        if timezone.now() < self.start_date:
            return self.start_date

        elif self.repeat_frequency:
            return self._next_occurrence(self.start_date, last=self.repeat_frequency_end_date)

        return None

    @property
    def next_end_date(self) -> datetime.datetime | None:
        if not self.end_date:
            return None

        if timezone.now() < self.end_date:
            return self.end_date

        elif self.repeat_frequency:
            # The repeat end date is the last time the event may start, it still ends afterwards
            last = (self.repeat_frequency_end_date + (self.end_date - self.start_date)
                    if self.repeat_frequency_end_date else None)
            return self._next_occurrence(self.end_date, last=last)

        return None

    def regenerate_notifications(self):
        """Regenerate notifications for the event"""
        if not self.repeat_frequency and self.end_date and timezone.now() > self.end_date:
            return

        self.notification_channel.notificationobject_set.filter(timestamp__gte=timezone.now()).all().delete()

        if self.next_start_date:
            self.notify_start(NotificationObject.Action.CREATED,
                              timestamp=self.next_start_date,
                              message=f"Event started: {self.title}")

        if self.next_end_date:
            self.notify_end(NotificationObject.Action.CREATED,
                            timestamp=self.next_end_date,
                            message=f"Event ended: {self.title}")

        # Followers of a single occurrence have no channel subscription to get these from
        for subscription in self.scheduleeventsubscription_set.filter(occurrence_start__isnull=False):
            subscription.sync_notifications()

    def occurrence_dates(self, start: datetime.datetime) -> tuple[datetime.datetime, datetime.datetime | None] | None:
        """
        The start and end of the occurrence that starts at the given time (to the millisecond),
        None if the event has no such occurrence.
        """
        if not self.repeat_frequency:
            same = abs(start - self.start_date) < recurrence.SAME_TIME
            return (self.start_date, self.end_date) if same else None

        index = recurrence.occurrence_index(first=self.start_date,
                                            frequency=self.repeat_frequency,
                                            tz=self.zone_info,
                                            at=start,
                                            last=self.repeat_frequency_end_date)
        if index is None:
            return None

        end = (recurrence.occurrence(self.end_date, self.repeat_frequency, index, self.zone_info)
               if self.end_date else None)
        return recurrence.occurrence(self.start_date, self.repeat_frequency, index, self.zone_info), end

    def event_subscribe(self, user,
                        user_tags: list[str] = None,
                        locked: bool = True,
                        reminders: list[int] = None,
                        occurrence_start: datetime.datetime = None):
        """
        Subscribes the user to the event.
        :param occurrence_start: Start of the one occurrence of a repeating event to follow, leave empty to follow all.
        """
        if not (self.active and self.is_live):
            raise ValidationError("Event is not active or has already ended.")

        if occurrence_start is not None:
            dates = self.occurrence_dates(occurrence_start)
            if dates is None:
                raise ValidationError("Event has no occurrence starting at that time.")

            if (dates[1] or dates[0]) < timezone.now():
                raise ValidationError("Occurrence has already ended.")

            occurrence_start = dates[0]

        user_schedule = ScheduleUser.objects.get(schedule=self.schedule, user=user)
        ScheduleEventSubscription.objects.update_or_create(event=self,
                                                           schedule_user=user_schedule,
                                                           defaults=dict(tags=user_tags,
                                                                         reminders=reminders,
                                                                         locked=locked,
                                                                         occurrence_start=occurrence_start))

    def event_unsubscribe(self, user):
        with transaction.atomic():
            user_schedule = ScheduleUser.objects.get(schedule=self.schedule, user=user)
            ScheduleEventSubscription.objects.get(event=self, schedule_user=user_schedule).delete()

    @classmethod
    def post_save(cls, instance, created, update_fields: list[str] = None, *args, **kwargs):
        # Remove unrelated subscriptions and migrate new and existing subscribers to a new tag
        if not created and (update_fields and 'tag' in update_fields):
            schedule_event_user_datas = ScheduleEventSubscription.objects.filter(event=instance, locked=False)
            new_active_subscribers = ScheduleTagSubscription.objects.filter(schedule_tag=instance.tag)
            locked_users = ScheduleEventSubscription.objects.filter(event=instance,
                                                                    locked=True).values_list('schedule_user__user',
                                                                                             flat=True)

            # Delete subscriptions that are not in the new tag
            for i in schedule_event_user_datas:
                subscription_exists = new_active_subscribers.filter(schedule_user=i.schedule_user).exists()
                if not subscription_exists:
                    instance.event_unsubscribe(user=i.schedule_user.user)

            # Migrate subscriptions that are in the new tag (excluding users with locked event subscriptions)
            for i in new_active_subscribers.exclude(schedule_user__user__in=locked_users):
                instance.event_subscribe(user=i.schedule_user.user, reminders=i.reminders, locked=False)

        # Repeat Frequency and notification management
        if instance.repeat_frequency:
            # The crontab runs in the event's timezone, so that it keeps its time of day when the clocks change
            end_date = instance.end_date.astimezone(instance.zone_info)

            cron_data = dict()
            if instance.repeat_frequency == instance.Frequency.WEEKLY:
                cron_data['day_of_week'] = str(end_date.weekday())

            elif instance.repeat_frequency == instance.Frequency.MONTHLY:
                cron_data['day_of_month'] = end_date.day

            elif instance.repeat_frequency == instance.Frequency.YEARLY:
                cron_data['month_of_year'] = end_date.month
                cron_data['day_of_month'] = end_date.day

            crontabs = CrontabSchedule.objects.filter(minute=end_date.minute,
                                                      hour=end_date.hour,
                                                      timezone=instance.zone_info,
                                                      **cron_data)

            if crontabs.exists():
                cron_schedule = crontabs.first()

            else:
                cron_schedule = CrontabSchedule(minute=end_date.minute,
                                                hour=end_date.hour,
                                                timezone=instance.zone_info,
                                                **cron_data)

                cron_schedule.full_clean()
                cron_schedule.save()

            # If not created, update the instance task with a new crontab schedule
            task = PeriodicTask.objects.filter(name=f"schedule_event_{instance.id}").first()
            if task:
                if task.crontab != cron_schedule or task.expires != instance.repeat_frequency_end_date:
                    task.start_date = instance.start_date
                    task.crontab = cron_schedule
                    task.expires = instance.repeat_frequency_end_date
                    task.save()

            else:
                periodic_task = PeriodicTask.objects.create(name=f"schedule_event_{instance.id}",
                                                            task="schedule.tasks.event_notify",
                                                            kwargs=json.dumps(dict(event_id=instance.id)),
                                                            crontab=cron_schedule,
                                                            start_time=instance.start_date,
                                                            expires=instance.repeat_frequency_end_date)
                periodic_task.full_clean()
                periodic_task.save()

                instance.regenerate_notifications()

        elif created:
            # A repeating event is given its notifications along with its periodic task above
            instance.regenerate_notifications()

        if not created:
            if update_fields and any([x in update_fields for x in ['end_date',
                                                                   'start_date',
                                                                   'repeat_frequency',
                                                                   'repeat_frequency_end_date',
                                                                   'timezone']]):
                instance.regenerate_notifications()


post_save.connect(ScheduleEvent.post_save, ScheduleEvent)


class ScheduleEventSubscription(BaseModel):
    event = models.ForeignKey(ScheduleEvent, on_delete=models.CASCADE)
    schedule_user = models.ForeignKey('schedule.ScheduleUser', on_delete=models.CASCADE)
    reminders = ArrayField(models.PositiveIntegerField(), size=10, null=True, blank=True)
    tags = ArrayField(base_field=models.CharField(max_length=100), size=10, null=True, blank=True,
                      help_text="A list of user-defined tags")
    locked = models.BooleanField(default=True, help_text="If set to true and user unsubscribes from the tag related "
                                                         "to the event, the event will remain subscribed.")
    occurrence_start = models.DateTimeField(null=True, blank=True,
                                            help_text="Start of the one occurrence of a repeating event that the user "
                                                      "follows. Leave empty to follow every occurrence.")

    class Meta:
        constraints = [models.UniqueConstraint('event', 'schedule_user', name='eventscheduleuser_unique')]

    def upcoming_notifications(self):
        """The user's notifications about the event that have yet to be shown, reminders are shown ahead of the event"""
        return Notification.objects.filter(user=self.schedule_user.user,
                                           notification_object__channel=self.event.notification_channel
                                           ).annotate(due=ExpressionWrapper(
                                               F('notification_object__timestamp')
                                               - F('reminder') * datetime.timedelta(seconds=1),
                                               output_field=models.DateTimeField())
                                           ).filter(due__gt=timezone.now())

    def sync_notifications(self):
        """
        Gives the user the notifications the event has already generated for the occurrences they follow.
        Those are made when the event repeats, so someone subscribing in between would miss them.
        """
        self.upcoming_notifications().delete()

        occurrence = (self.event.occurrence_dates(self.occurrence_start)
                      if self.occurrence_start else None)
        notification_objects = self.event.notification_channel.notificationobject_set.filter(
            timestamp__gt=timezone.now(), tag__in=['start', 'end'])

        notifications = []
        for notification_object in notification_objects:
            if self.occurrence_start:
                expected = None if occurrence is None else occurrence[1 if notification_object.tag == 'end' else 0]
                if notification_object.timestamp != expected:
                    continue

            notifications.append(Notification(user=self.schedule_user.user, notification_object=notification_object))

            # Reminders are only made for the start, and not for those that should have been shown by now
            if notification_object.tag == 'start':
                for reminder in self.reminders or []:
                    if notification_object.timestamp - datetime.timedelta(seconds=reminder) > timezone.now():
                        notifications.append(Notification(user=self.schedule_user.user,
                                                          notification_object=notification_object,
                                                          reminder=reminder))

        Notification.objects.bulk_create(notifications, ignore_conflicts=True)

    @classmethod
    def post_save(cls, instance, *args, **kwargs):
        channel = instance.event.notification_channel
        user = instance.schedule_user.user

        if instance.occurrence_start:
            channel.unsubscribe(user=user)

        else:
            channel.subscribe(user=user,
                              tags=['start', 'end'],
                              reminders=(None if not instance.reminders
                                         else [instance.reminders, None]))

        instance.sync_notifications()

    @classmethod
    def pre_delete(cls, instance, *args, **kwargs):
        instance.event.notification_channel.unsubscribe(user=instance.schedule_user.user)
        instance.upcoming_notifications().delete()


post_save.connect(ScheduleEventSubscription.post_save, ScheduleEventSubscription)
pre_delete.connect(ScheduleEventSubscription.pre_delete, ScheduleEventSubscription)


class ScheduleTagSubscription(BaseModel):
    schedule_user = models.ForeignKey('schedule.ScheduleUser', on_delete=models.CASCADE)
    schedule_tag = models.ForeignKey(ScheduleTag, on_delete=models.CASCADE)
    reminders = ArrayField(models.PositiveIntegerField(), size=10, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['schedule_user', 'schedule_tag'],
                                    name='unique_schedule_tag_subscription')
        ]
        triggers = [
            pgtrigger.Protect(name='prevent_update_schedule_tag_subscription',
                              operation=pgtrigger.Update)
        ]

    @classmethod
    def post_save(cls, instance, created, *args, **kwargs):
        events = instance.schedule_tag.scheduleevent_set.filter(Q(start_date__gte=timezone.now())
                                                                | Q(end_date__isnull=True)
                                                                | Q(end_date__gt=timezone.now())
                                                                | Q(repeat_frequency__isnull=False), active=True)

        # What the user chose for an event themselves is not changed by the tag
        chosen = ScheduleEventSubscription.objects.filter(schedule_user=instance.schedule_user, locked=True)

        with transaction.atomic():
            for event in filter(lambda e: e.is_live, events.exclude(scheduleeventsubscription__in=chosen)):
                event.event_subscribe(user=instance.schedule_user.user, locked=False, reminders=instance.reminders)

    def delete_user_events(self, include_locked: bool = False, user_tags: list[str] | None = None):
        filters = dict()
        if not include_locked:
            filters['scheduleeventsubscription__locked'] = False

        if user_tags:
            filters['scheduleeventsubscription__user'] = self.schedule_user.user
            filters['scheduleeventsubscription__tag__in'] = user_tags

        events = ScheduleEvent.objects.filter(
            schedule=self.schedule_user.schedule,
            tag=self.schedule_tag,
            scheduleeventsubscription__schedule_user__user=self.schedule_user.user,
            **filters)

        with transaction.atomic():
            for event in events:
                event.event_unsubscribe(user=self.schedule_user.user)

    @classmethod
    def pre_delete(cls, instance, *args, **kwargs):
        instance.delete_user_events()


post_save.connect(ScheduleTagSubscription.post_save, ScheduleTagSubscription)
pre_delete.connect(ScheduleTagSubscription.pre_delete, ScheduleTagSubscription)


# TODO add active status, should be possible to restore ScheduleUser when re-joining
class ScheduleUser(BaseModel):
    subscribe_to_new_notification_tags = models.BooleanField(default=False, blank=True)
    reminders = ArrayField(models.PositiveIntegerField(), size=10, null=True, blank=True)
    notification_tags = models.ManyToManyField(ScheduleTag, blank=True, through=ScheduleTagSubscription)

    user = models.ForeignKey('user.User', on_delete=models.CASCADE)
    schedule = models.ForeignKey(Schedule, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('user', 'schedule')

    def tag_unsubscribe(self,
                        tag_ids: list[int] | None,
                        include_locked: bool = False) -> None:
        """
        Deletes all notifications and tag subscriptions for the user and schedule.
        :param tag: Relevant tags to target, leave empty to delete all notification subscriptions.
        :param user_tag: Relevant user tags to target, leave empty to delete all notification subscriptions.
        :param include_locked: Whether to include user-locked events or not.
        :return: None
        """
        with transaction.atomic():
            ScheduleTagSubscription.objects.filter(schedule_user=self, schedule_tag__in=tag_ids).delete()

    def user_tag_unsubscribe(self,
                             user_tag_ids: list[int] | None,
                             include_locked: bool = False) -> None:
        """
        Deletes all notifications and tag subscriptions for the user and schedule.
        :param tag: Relevant tags to target, leave empty to delete all notification subscriptions.
        :param user_tag: Relevant user tags to target, leave empty to delete all notification subscriptions.
        :param include_locked: Whether to include user-locked events or not.
        :return: None
        """
        with transaction.atomic():
            tags = ScheduleEventSubscription.objects.filter(schedule_user=self)


def generate_schedule(sender, instance, created, *args, **kwargs):
    if created and issubclass(sender, ScheduleModel):
        Schedule.objects.create(created_by=instance)


class ScheduleModel(models.Model):
    schedule_relations = GenericRelation(Schedule, on_delete=models.CASCADE)

    class Meta:
        abstract = True

    @property
    def schedule(self):
        return self.schedule_relations.first()

    @classmethod
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        models.signals.post_save.connect(generate_schedule, sender=cls)
