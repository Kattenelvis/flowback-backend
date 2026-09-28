from rest_framework.exceptions import PermissionDenied

from flowback.group.selectors.permission import group_user_permissions
from flowback.user.models import User, Report
from flowback.poll.models import Poll
from django.db.models import Exists, OuterRef, Value, Case, When, Q
from django.db.models.fields import CharField
from flowback.group.models import GroupThread


def reports_list(fetched_by: User, group_id: int = None):
    is_staff = fetched_by.is_staff or fetched_by.is_superuser

    # Group admins may view reports of their own group, server staff may view all reports
    if group_id is not None and not is_staff:
        group_user_permissions(user=fetched_by, group=group_id, permissions=['admin'])

    elif not is_staff:
        raise PermissionDenied('Only server staff members can view reports')

    qs = Report.objects.all()
    if group_id is not None:
        qs = qs.filter(group_id=group_id)

    return qs.order_by('-created_at').annotate(
        # If the post being reported is still active, then the admin action is "nothing". If the post has been deleted, then the admin action is "deleted".
        admin_action=Case(
            When(
                Q(post_type='poll', post_id__isnull=False)
                & Q(Exists(Poll.objects.filter(id=OuterRef('post_id'), active=True))),
                then=Value("nothing")
            ),
            When(
                Q(post_type='thread', post_id__isnull=False)
                & Q(Exists(GroupThread.objects.filter(id=OuterRef('post_id'), active=True))),
                then=Value("nothing")
            ),
            default=Value("deleted"),
            output_field=CharField()
        )
    )
