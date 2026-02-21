from rest_framework.exceptions import PermissionDenied

from flowback.user.models import User, Report
from flowback.poll.models import Poll
from django.db.models import Exists, OuterRef, Value, Case, When, Q
from django.db.models.fields import CharField
from flowback.group.models import GroupThread


def reports_list(fetched_by: User):
    if not (fetched_by.is_staff or fetched_by.is_superuser):
        raise PermissionDenied('Only server staff members can view reports')

    return Report.objects.all().order_by('-created_at').annotate(
        # If the post being reported is still active, then the admin action is "nothing". If the post has been deleted, then the admin action is "deleted".
        admin_action=Case(
            When(
                Q(Exists(Poll.objects.filter(id=OuterRef('post_id'), active=True)))
                & Q(Exists(GroupThread.objects.filter(id=OuterRef('post_id'), active=True))),
                then=Value("nothing")
            ),
            default=Value("deleted"),
            output_field=CharField()
        )
    )
