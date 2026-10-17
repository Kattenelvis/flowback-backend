from celery import shared_task
from django.utils import timezone
from django_celery_beat.models import PeriodicTask

from flowback.schedule.models import ScheduleEvent


@shared_task
def event_notify(event_id: int):
    """
    :param event_id:  ScheduleEvent id
    """
    event = ScheduleEvent.objects.filter(id=event_id).first()

    # Stop notifying if event is removed
    if not event or not event.repeat_frequency:
        PeriodicTask.objects.filter(name=f"schedule_event_{event_id}").delete()
        return

    # Skip notify if scheduled at a later date
    if event.start_date > timezone.now():
        return

    # Followers of a single occurrence are done once it has been held
    event.scheduleeventsubscription_set.filter(occurrence_start__lt=timezone.now()).delete()

    # Past the repeat end date there is no next occurrence, which leaves no notifications to create
    event.regenerate_notifications()
