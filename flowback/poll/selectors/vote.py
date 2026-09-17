import django_filters

from flowback.common.services import get_object
from flowback.poll.classes import poll_type as pt
from flowback.poll.models import Poll
from flowback.poll.phases import PollDelegateVoting
from flowback.user.models import User
from flowback.group.selectors.permission import group_user_permissions


class BaseDelegatePollVoteFilter(django_filters.FilterSet):
    class Meta:
        model = PollDelegateVoting
        fields = dict(poll_id=['exact'])


class BasePollDelegateVotingFilter(django_filters.FilterSet):
    delegate_pool_id = django_filters.NumberFilter(field_name='created_by_id')

    class Meta:
        model = PollDelegateVoting
        fields = dict(poll_id=['exact'])


def delegate_poll_vote_list(*, fetched_by: User, group_id: int, **filters):
    filters = filters or {}
    group_user_permissions(user=fetched_by, group=group_id)
    qs = PollDelegateVoting.objects.filter(poll__created_by__group_id=group_id).distinct()
    return BaseDelegatePollVoteFilter(filters, qs).qs


def poll_vote_list(*, fetched_by: User, poll_id: int, delegates: bool = False, filters=None):
    filters = filters or {}
    poll = get_object(Poll, id=poll_id)
    return pt.of(poll).vote_list_qs(fetched_by=fetched_by, delegates=delegates, filters=filters)


def poll_delegates_list(*, fetched_by: User, poll_id: int, filters=None):
    filters = filters or {}

    poll = get_object(Poll, id=poll_id)
    group_user_permissions(user=fetched_by, group=poll.created_by.group.id)

    qs = PollDelegateVoting.objects.filter(poll=poll).all()
    return BasePollDelegateVotingFilter(filters, qs).qs
