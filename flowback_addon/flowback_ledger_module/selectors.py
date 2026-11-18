import django_filters

from flowback.user.models import User
from .models import Account, Transaction


class BaseAccountFilter(django_filters.FilterSet):
    order_by = django_filters.OrderingFilter(
        fields=(('created_at', 'created_at_asc'),
                ('-created_at', 'created_at_desc'))
    )

    class Meta:
        model = Account
        fields = {
            'id': ['exact'],
        }


def account_list(*, user: User, filters=None):
    filters = filters or {}

    qs = Account.objects.filter(user=user).order_by('id')

    return BaseAccountFilter(filters, qs).qs


class BaseTransactionFilter(django_filters.FilterSet):
    order_by = django_filters.OrderingFilter(
        fields=(('created_at', 'created_at_asc'),
                ('-created_at', 'created_at_desc'),
                ('date', 'date_asc'),
                ('-date', 'date_desc'))
    )

    # Both bounds are inclusive and compare the calendar date only
    date_after = django_filters.DateFilter(field_name='date', lookup_expr='date__gte')
    date_before = django_filters.DateFilter(field_name='date', lookup_expr='date__lte')
    description = django_filters.CharFilter(field_name='description', lookup_expr='icontains')
    account_ids = django_filters.BaseInFilter(field_name='account_id', lookup_expr='in')

    class Meta:
        model = Transaction
        fields = ['id']


def transaction_list(*, user: User, filters=None):
    filters = dict(filters or {})

    # The filterset expects a comma separated string for the "in" lookup
    if 'account_ids' in filters:
        filters['account_ids'] = ','.join(str(account_id) for account_id in filters['account_ids'])

        if not filters['account_ids']:
            del filters['account_ids']

    qs = (Transaction.objects
          .filter(account__user=user)
          .select_related('account', 'account__user')
          .order_by('-date', '-id'))

    return BaseTransactionFilter(filters, qs).qs
