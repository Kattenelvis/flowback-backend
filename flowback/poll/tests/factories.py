import random

import factory
from django.utils import timezone
from future.backports.datetime import timedelta

from flowback.common.tests import fake
from flowback.group.tests.factories import GroupUserFactory, GroupUserDelegatePoolFactory, GroupTagsFactory, \
    GroupKPIFactory, GroupKPIValueFactory

from flowback.poll.models import Poll
from flowback.poll.phases import (PollAreaStatement,
                                  PollAreaStatementSegment,
                                  PollAreaStatementVote,
                                  PollDelegateVoting,
                                  PollPredictionBet,
                                  PollPredictionStatement,
                                  PollPredictionStatementSegment,
                                  PollPredictionStatementVote,
                                  PollProposal,
                                  PollProposalKPI,
                                  PollProposalKPIBet,
                                  PollProposalKPIVote,
                                  PollProposalTypeSchedule,
                                  PollVoting,
                                  PollVotingTypeCardinal)
from flowback.poll.tests.utils import generate_poll_phase_kwargs


class PollFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Poll

    created_by = factory.SubFactory(GroupUserFactory)
    title = factory.LazyAttribute(lambda _: fake.unique.first_name().lower())
    description = factory.LazyAttribute(lambda _: fake.bs())
    poll_type = Poll.PollType.SCORE
    dynamic = False

    start_date = factory.LazyAttribute(lambda _: timezone.now())
    area_vote_end_date = factory.LazyAttribute(lambda _: timezone.now() + timezone.timedelta(hours=1))
    proposal_end_date = factory.LazyAttribute(lambda _: timezone.now() + timezone.timedelta(hours=2))
    prediction_statement_end_date = factory.LazyAttribute(lambda _: timezone.now() + timezone.timedelta(hours=3))
    prediction_bet_end_date = factory.LazyAttribute(lambda _: timezone.now() + timezone.timedelta(hours=4))
    delegate_vote_end_date = factory.LazyAttribute(lambda _: timezone.now() + timezone.timedelta(hours=5))
    vote_end_date = factory.LazyAttribute(lambda _: timezone.now() + timezone.timedelta(hours=6))
    end_date = factory.LazyAttribute(lambda _: timezone.now() + timezone.timedelta(hours=7))


class PollProposalFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PollProposal

    @factory.post_generation
    def generate_schedule_event(obj, create, extracted, **kwargs):
        if not create:
            return

        if obj.poll.poll_type == Poll.PollType.SCHEDULE:
            PollProposalTypeScheduleFactory(proposal=obj, **kwargs)
    
    created_by = factory.SubFactory(GroupUserFactory)
    poll = factory.SubFactory(PollFactory)
    title = factory.LazyAttribute(lambda _: fake.unique.first_name())
    description = factory.LazyAttribute(lambda _: fake.bs())


class PollProposalTypeScheduleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PollProposalTypeSchedule

    event_start_date = factory.LazyAttribute(lambda _: timezone.now() + timedelta(days=1))
    event_end_date = factory.LazyAttribute(lambda _: timezone.now() + timedelta(days=2))
    proposal = factory.SubFactory(PollProposalFactory, poll__poll_type=Poll.PollType.SCHEDULE)


class PollVotingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PollVoting

    created_by = factory.SubFactory(GroupUserFactory)
    poll = factory.SubFactory(PollFactory)


class PollDelegateVotingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PollDelegateVoting

    created_by = factory.SubFactory(GroupUserDelegatePoolFactory)
    poll = factory.SubFactory(PollFactory)


class PollVotingTypeCardinalFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PollVotingTypeCardinal

    proposal = factory.SubFactory(PollProposalFactory)
    score = factory.LazyAttribute(lambda _: fake.pyint())


class PollPredictionStatementFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PollPredictionStatement

    created_by = factory.SubFactory(GroupUserFactory, group=factory.SelfAttribute('..poll.created_by.group'))
    poll = factory.SubFactory(PollFactory, **generate_poll_phase_kwargs('proposal'))
    title = factory.LazyAttribute(lambda _: fake.name())
    description = factory.LazyAttribute(lambda _: fake.bs())
    end_date = factory.LazyAttribute(lambda _: timezone.now() + timezone.timedelta(hours=99))


class PollPredictionBetFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PollPredictionBet

    prediction_statement = factory.SubFactory(PollPredictionStatementFactory)
    created_by = factory.SubFactory(GroupUserFactory)
    score = factory.LazyAttribute(lambda _: fake.pyint(min_value=0, max_value=5))


class PollPredictionStatementSegmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PollPredictionStatementSegment

    prediction_statement = factory.SubFactory(PollPredictionStatementFactory)
    proposal = factory.SubFactory(PollProposalFactory)
    is_true = factory.LazyAttribute(lambda _: fake.pybool())


class PollPredictionStatementVoteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PollPredictionStatementVote

    prediction_statement = factory.SubFactory(PollPredictionStatementFactory)
    created_by = factory.SubFactory(GroupUserFactory)
    vote = factory.LazyAttribute(lambda _: fake.pybool())


class PollProposalKPIFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PollProposalKPI

    proposal = factory.SubFactory(PollProposalFactory)
    kpi_value = factory.SubFactory(GroupKPIValueFactory)


class PollProposalKPIBetFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PollProposalKPIBet

    created_by = factory.SubFactory(GroupUserFactory)
    proposal_kpi = factory.SubFactory(PollProposalKPIFactory)
    weight = factory.LazyAttribute(lambda _: random.randint(1, 999999))


class PollProposalKPIVoteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PollProposalKPIVote

    created_by = factory.SubFactory(GroupUserFactory)
    proposal_kpi = factory.SubFactory(PollProposalKPIFactory)


class PollAreaStatementFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PollAreaStatement

    created_by = factory.SubFactory(GroupUserFactory)
    poll = factory.SubFactory(PollFactory, **generate_poll_phase_kwargs('area'))


class PollAreaStatementSegmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PollAreaStatementSegment

    poll_area_statement = factory.SubFactory(PollAreaStatementFactory)
    tag = factory.SubFactory(GroupTagsFactory)


class PollAreaStatementVoteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PollAreaStatementVote

    created_by = factory.SubFactory(GroupUserFactory)
    poll_area_statement = factory.SubFactory(PollAreaStatementFactory)
    vote = factory.LazyAttribute(lambda _: fake.pybool())
