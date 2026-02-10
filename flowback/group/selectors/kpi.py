import django_filters

from flowback.group.models import GroupKPI
from flowback.group.selectors.permission import group_user_permissions
from flowback.user.models import User


class BaseGroupKPIFilter(django_filters.FilterSet):
    class Meta:
        model = GroupKPI
        fields = dict(id=['exact'],
                      name=['exact', 'icontains'],
                      description=['exact', 'icontains'],
                      active=['exact'])


def group_kpi_list(*, group_id: int, fetched_by: User, filters=None):
    filters = filters or {}
    group_user = group_user_permissions(user=fetched_by, group=group_id)

    qs = GroupKPI.objects.filter(group_id=group_id)

    if not group_user.is_admin:
        qs = qs.filter(active=True)

    return BaseGroupKPIFilter(filters, qs).qs
