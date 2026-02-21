from rest_framework.exceptions import PermissionDenied

from flowback.user.models import User, Report
from flowback.poll.models import Poll
from django.db.models import Exists, OuterRef, Value, Case, When
from flowback.group.models import GroupThread


def reports_list(fetched_by: User):
    if not (fetched_by.is_staff or fetched_by.is_superuser):
        raise PermissionDenied('Only server staff members can view reports')

    print(list(Poll.objects.filter(id__in=Report.objects.values_list('post_id', flat=True))), "QUERY")

    return Report.objects.all().order_by('-created_at').annotate(
        admin_action=Case(
            When(Exists(Poll.objects.filter(id=OuterRef('post_id'), active=True)), then=Value("nothing")),
            default=Value("deleted")
        ))
