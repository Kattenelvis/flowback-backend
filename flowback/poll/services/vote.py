from rest_framework.exceptions import ValidationError

from flowback.common.services import get_object
from flowback.group.models import GroupUserDelegatePool
from flowback.group.notify import notify_group_user_delegate_pool_poll_vote_update
from flowback.notification.models import NotificationChannel
from flowback.poll.models import Poll
from flowback.group.selectors.permission import group_user_permissions


def poll_proposal_vote_update(*, user_id: int, poll_id: int, data: dict) -> None:
    poll = get_object(Poll, id=poll_id)
    group_user = group_user_permissions(user=user_id,
                                        group=poll.created_by.group.id,
                                        permissions=['allow_vote', 'admin'])

    poll.check_phase('vote', 'dynamic', 'schedule')
    poll.poll_type_new.update_vote(group_user=group_user, data=data)


def poll_proposal_delegate_vote_update(*, user_id: int, poll_id: int, data) -> None:
    poll = Poll.objects.get(id=poll_id)
    group_user = group_user_permissions(user=user_id, group=poll.created_by.group.id)

    try:
        delegate_pool = GroupUserDelegatePool.objects.get(groupuserdelegate__group_user=group_user)
    except GroupUserDelegatePool.DoesNotExist:
        raise ValidationError("User is not a delegate")

    if group_user.group.id != poll.created_by.group.id:
        raise ValidationError('Permission denied')

    poll.check_phase('delegate_vote', 'dynamic', 'schedule')
    poll.poll_type_new.update_delegate_vote(delegate_pool=delegate_pool, data=data)

    notify_group_user_delegate_pool_poll_vote_update(action=NotificationChannel.Action.UPDATED,
                                                     message="A Delegate you subscribed to has "
                                                             "added/updated their vote(s) on a poll",
                                                     poll=poll,
                                                     delegate_pool=delegate_pool)
