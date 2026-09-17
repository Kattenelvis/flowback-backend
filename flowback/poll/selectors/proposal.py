from django.db.models import F

from flowback.common.services import get_object
from flowback.poll.classes import poll_type as pt
from flowback.poll.filters import BasePollProposalScheduleFilter
from flowback.poll.models import Poll
from flowback.poll.phases import PollProposal
from flowback.user.models import User
from flowback.group.selectors.permission import group_user_permissions


def poll_proposal_list(*, fetched_by: User, poll_id: int, filters=None):
    filters = filters or {}
    fieldset = ['id', 'poll_id', 'created_by', 'title', 'description', 'attachments', 'blockchain_id', 'score',
                'pollproposaltypeschedule']
    admin = fetched_by.is_superuser

    if poll_id:
        poll = get_object(Poll, id=poll_id)

        if not poll.public:
            group_user = group_user_permissions(user=fetched_by, group=poll.created_by.group.id)
            admin = group_user.is_admin

        qs = PollProposal.objects.filter(created_by__group_id=poll.created_by.group.id, poll=poll, active=True)\
            .order_by(F('score').desc(nulls_last=True))

        if poll.created_by.group.hide_poll_users and not admin:
            fieldset.remove('created_by')
            [filters.pop(key, None) for key in ['created_by_user_id_list', 'created_by']]
            qs = qs.defer('created_by').all()

        return pt.of(poll).proposal_filter_class()(filters, qs).qs


def poll_user_schedule_list(*, fetched_by: User, filters=None):
    filters = filters or {}
    qs = PollProposal.objects.filter(created_by__group__groupuser__user__in=[fetched_by],
                                     poll__poll_type=Poll.PollType.SCHEDULE,
                                     poll__status=1,
                                     active=True).order_by('poll', 'score')\
        .distinct('poll').all()

    return BasePollProposalScheduleFilter(filters, qs).qs
