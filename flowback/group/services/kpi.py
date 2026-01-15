from .permission import group_user_permissions
from ..models import GroupKPI


def group_kpi_create(user_id: int, group_id: int, name: str, values: list[int], description: str = None):
    group_user_permissions(user=user_id, group=group_id, permissions=['admin'])

    kpi = GroupKPI(group_id=group_id, name=name, values=values, description=description)
    kpi.full_clean()
    kpi.save()

    return kpi


def group_kpi_update(user_id: int, kpi_id: int, active: bool = True):
    kpi = GroupKPI.objects.get(id=kpi_id)

    group_user_permissions(user=user_id, group=kpi.group_id, permissions=['admin'])

    kpi.active = active
    kpi.save()
