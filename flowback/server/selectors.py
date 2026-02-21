from rest_framework.exceptions import PermissionDenied

from flowback.user.models import User, Report
from flowback.poll.models import Poll
from django.db.models import Q, Exists, OuterRef, F, Subquery, Value
from flowback.group.models import GroupThread


def reports_list(fetched_by: User):
    if not (fetched_by.is_staff or fetched_by.is_superuser):
        raise PermissionDenied('Only server staff members can view reports')

    return Report.objects.all().order_by('-created_at').annotate(
        admin_action=Value("nothing" if Exists(Subquery(Poll.objects.filter(id=OuterRef('post_id')))) else "deleted"))
