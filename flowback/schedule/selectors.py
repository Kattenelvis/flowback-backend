# Schedule Event List (with multiple schedule id support)
import django_filters
from django.contrib.postgres.aggregates import ArrayAgg
from django.db.models import OuterRef, Subquery, Exists, Q

from flowback.common.filters import NumberInFilter
from flowback.schedule.models import ScheduleEvent, ScheduleEventSubscription, ScheduleTagSubscription, Schedule
from flowback.user.models import User


class ScheduleEventBaseFilter(django_filters.FilterSet):
    ids = NumberInFilter(field_name='id')
    schedule_origin_name = django_filters.CharFilter(field_name='schedule__content_type__model',
                                                     lookup_expr='iexact')
    schedule_origin_id = NumberInFilter(field_name='schedule__object_id')
    origin_name = django_filters.CharFilter(field_name='content_type__model', lookup_expr='iexact')
    origin_ids = NumberInFilter(field_name='object_id')
    schedule_ids = NumberInFilter(field_name='schedule_id')
    title = django_filters.CharFilter(lookup_expr='iexact')
    description = django_filters.CharFilter(lookup_expr='icontains')
    active = django_filters.BooleanFilter()
    tag_ids = NumberInFilter(field_name='tag_id')
    assignee_user_ids = NumberInFilter(field_name='assignees__user__id')
    repeat_frequency__isnull = django_filters.BooleanFilter(field_name='repeat_frequency', lookup_expr='isnull')
    user_tags = django_filters.CharFilter(lookup_expr='iexact')
    subscribed = django_filters.BooleanFilter()
    locked = django_filters.BooleanFilter()
    tag_name = django_filters.CharFilter(lookup_expr='iexact', field_name='tag__name')

    # Events in a window of time, like what a calendar shows. start_date and end_date only describe the first
    # occurrence of a repeating event, so the lookups on them can't tell if it has a later occurrence in the window.
    # For those the client gets the event once, and works out the occurrences itself.
    window_start = django_filters.IsoDateTimeFilter(method='filter_window_start')
    window_end = django_filters.IsoDateTimeFilter(field_name='start_date', lookup_expr='lt')

    order_by = django_filters.OrderingFilter(fields=(('created_at', 'created_at_asc'),
                                                     ('-created_at', 'created_at_desc'),
                                                     ('start_date', 'start_date_asc'),
                                                     ('-start_date', 'start_date_desc'),
                                                     ('end_date', 'end_date_asc'),
                                                     ('-end_date', 'end_date_desc')))

    class Meta:
        model = ScheduleEvent
        fields = dict(start_date=['lt', 'gt', 'exact'],
                      end_date=['lt', 'gt', 'exact'])

    def filter_window_start(self, queryset, name, value):
        # An event without an end is over when it starts, a repeating one when it stops repeating
        one_off_not_over = (Q(repeat_frequency__isnull=True)
                            & (Q(end_date__gte=value) | Q(end_date__isnull=True, start_date__gte=value)))
        repeating_not_over = (Q(repeat_frequency__isnull=False)
                              & (Q(repeat_frequency_end_date__isnull=True) | Q(repeat_frequency_end_date__gte=value)))

        return queryset.filter(one_off_not_over | repeating_not_over)


# Offset pagination skips and repeats rows unless every page is sorted the same way, so ties are broken by id
def _stable_order(queryset, default_ordering: list[str]):
    return queryset.order_by(*(list(queryset.query.order_by) or default_ordering), 'id')


def schedule_event_list(*, user: User, filters=None):
    filters = filters or {}
    subscription_qs = ScheduleEventSubscription.objects.filter(event_id=OuterRef('id'),
                                                               schedule_user__user=user)

    qs = ScheduleEvent.objects.filter(
        schedule__scheduleuser__user=user
    ).annotate(reminders=Subquery(subscription_qs.values('reminders')),
               user_tags=Subquery(subscription_qs.values('tags')),
               locked=Subquery(subscription_qs.values('locked')),
               subscribed_occurrence=Subquery(subscription_qs.values('occurrence_start')),
               subscribed=Exists(subscription_qs)).all()

    return _stable_order(ScheduleEventBaseFilter(filters, qs).qs, ['start_date'])


class ScheduleTagSubscriptionBaseFilter(django_filters.FilterSet):
    origin_name = django_filters.CharFilter(field_name='schedule_user__schedule__content_type__model',
                                            lookup_expr='iexact')
    origin_ids = NumberInFilter(field_name='schedule_user__schedule__object_id')
    schedule_ids = NumberInFilter(field_name='schedule_user__schedule_id')
    tag_name = django_filters.CharFilter(field_name='schedule_tag__name')

    class Meta:
        model = ScheduleTagSubscription
        fields = dict(id=['exact'])


def schedule_tag_subscription_list(*, user: User, filters=None):
    filters = filters or {}

    qs = ScheduleTagSubscription.objects.filter(schedule_user__user=user).all()
    return ScheduleTagSubscriptionBaseFilter(filters, qs).qs


class ScheduleBaseFilter(django_filters.FilterSet):
    ids = NumberInFilter(field_name='id')
    origin_name = django_filters.CharFilter(field_name='content_type__model', lookup_expr='iexact')
    origin_ids = NumberInFilter(field_name='object_id')
    order_by = django_filters.OrderingFilter(fields=(('created_at', 'created_at_asc'),
                                                     ('-created_at', 'created_at_desc'),
                                                     ('content_type__model', 'origin_name_asc'),
                                                     ('-content_type__model', 'origin_name_desc')))

    class Meta:
        model = Schedule
        fields = dict(id=['exact'])


# Schedule list (incl. info about subscriptions, reminders, user tags and tags)
def schedule_list(*, user: User, filters=None):
    filters = filters or {}
    qs = Schedule.objects.filter(
        scheduleuser__user=user
    ).annotate(available_tags=ArrayAgg('scheduletag__name', distinct=True)).all()

    return _stable_order(ScheduleBaseFilter(filters, qs).qs, [])
