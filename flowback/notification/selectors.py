import datetime

import django_filters
from django.db import models
from django.db.models import ExpressionWrapper, F
from django.utils import timezone

from .models import NotificationChannel, NotificationObject, Notification, NotificationSubscription
from ..user.models import User


# A notification is shown when its object's timestamp comes, a reminder that many seconds before it
def _with_due_time(queryset):
    return queryset.annotate(due=ExpressionWrapper(F('notification_object__timestamp')
                                                   - F('reminder') * datetime.timedelta(seconds=1),
                                                   output_field=models.DateTimeField()))


class BaseNotificationFilter(django_filters.FilterSet):
    order_by = django_filters.OrderingFilter(fields=(('due', 'timestamp_asc'),
                                                     ('-due', 'timestamp_desc')))

    object_id = django_filters.NumberFilter(field_name='notification_object_id')
    message__icontains = django_filters.CharFilter(field_name='notification_object__message',
                                                   lookup_expr='icontains')
    action = django_filters.CharFilter(field_name='notification_object__action')
    timestamp__lt = django_filters.DateTimeFilter(field_name='due', lookup_expr='lt')
    timestamp__gt = django_filters.DateTimeFilter(field_name='due', lookup_expr='gt')

    channel_name = django_filters.CharFilter(field_name='notification_object__channel__content_type__model',
                                             lookup_expr='iexact')
    exclude_reminders = django_filters.BooleanFilter(method='filter_exclude_reminders')

    def filter_exclude_reminders(self, queryset, name, value):
        if value:
            return queryset.filter(reminder=0)

        return queryset

    class Meta:
        model = Notification
        fields = dict(id=['exact'],
                      read=['exact'])


def notification_list(*, user: User, filters=None):
    filters = filters or {}
    qs = _with_due_time(Notification.objects.filter(user=user)).filter(due__lte=timezone.now())

    return BaseNotificationFilter(filters, qs).qs


class BaseNotificationSubscriptionFilter(django_filters.FilterSet):
    channel_id = django_filters.CharFilter(field_name='channel_id')
    channel_name = django_filters.CharFilter(field_name='channel__content_type__model', lookup_expr='iexact')
    has_reminders = django_filters.BooleanFilter(method='filter_has_reminders')

    def filter_has_reminders(self, queryset, name, value):
        if value:
            return queryset.filter(notificationsubscriptiontag__reminders__isnull=False)

        return queryset

def notification_subscription_list(*, user: User, filters=None):
    filters = filters or {}
    qs = NotificationSubscription.objects.filter(user=user).all()
    return BaseNotificationSubscriptionFilter(filters, qs).qs
