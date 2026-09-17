from abc import ABC, abstractmethod

from django.db.models import Case, F, OuterRef, Subquery, Sum, When
from django.db.models.signals import pre_save
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from backend.settings import FLOWBACK_SCORE_VOTE_CEILING, FLOWBACK_SCORE_VOTE_FLOOR
from flowback.files.serializers import FileCollectionCreateSerializerMixin
from flowback.group.selectors.permission import group_user_permissions, permission_q
from flowback.group.serializers import GroupUserSerializer
from flowback.poll import tasks as _tasks
from flowback.poll.filters import (
    BasePollProposalFilter,
    BasePollProposalScheduleFilter,
    BasePollVoteCardinalFilter,
    BasePollVoteForAgainstFilter,
)
from flowback.poll.models import Poll
from flowback.poll.phases import (
    PollDelegateVoting,
    PollProposal,
    PollProposalTypeSchedule,
    PollVoting,
    PollVotingTypeCardinal,
    PollVotingTypeForAgainst,
)


_REGISTRY: dict[str, type["PollType"]] = {}


def register(poll_type: Poll.PollType):
    def decorator(cls):
        cls.poll_type = poll_type
        _REGISTRY[str(poll_type)] = cls
        return cls

    return decorator


def of(poll: Poll) -> "PollType":
    cls = _REGISTRY.get(poll.poll_type)
    if cls is None:
        raise ValidationError("Unknown poll type")
    return cls(poll)


class PollType(ABC):
    """Strategy: per-poll-type behavior. One subclass per Poll.PollType value, registered via @register."""

    poll_type: Poll.PollType

    def __init__(self, poll: Poll):
        self.poll = poll

    # --- Labels (per-type) ---

    @abstractmethod
    def labels(self) -> tuple: ...

    def finished(self) -> bool:
        now = timezone.now()
        return self.poll.end_date is not None and self.poll.end_date <= now

    # --- Phase navigation (depend only on labels — concrete on ABC) ---

    def current_phase(self) -> str:
        labels = self.labels()
        current_time = timezone.now()
        for x in reversed(range(len(labels))):
            if current_time >= labels[x][0]:
                return labels[x][2]
        return "waiting"

    def get_phase(
        self, phase: str, use_time_table: bool = False, field_name: bool = False
    ):
        time_table = self.labels() if not use_time_table else self.poll.time_table
        for x in reversed(range(len(time_table))):
            if phase == time_table[x][2]:
                if field_name:
                    return time_table[x][1]
                return time_table[x][0]
        raise Exception("Phase not found")

    def phase_exist(self, phase: str, raise_exception: bool = True) -> bool:
        phases = [label[2] for label in self.labels()]
        if phase in phases:
            return True
        if raise_exception:
            raise ValidationError(f'Poll phase "{phase}" does not exist')
        return False

    def check_phase(self, *phases: str, raise_exception: bool = True) -> bool:
        if not any(self.phase_exist(p, raise_exception=False) for p in phases):
            if not raise_exception:
                return False
            raise ValidationError("Action is unavailable for this poll")

        current = self.current_phase()
        if current not in phases:
            if not raise_exception:
                return False
            raise ValidationError(
                f"Poll is not in {' or '.join(phases)}, currently in {current}"
            )
        return True

    def validate_phases(self) -> None:
        labels = self.labels()
        if not all(x[0] is not None for x in labels):
            raise ValidationError(
                "Current poll type requires following fields to be filled: "
                + ", ".join(x[1] for x in labels)
            )

        min_space = self.poll.created_by.group.poll_phase_minimum_space
        for i in range(len(labels) - 1):
            phase = labels[i]
            next_phase = labels[i + 1]
            if phase[0] >= next_phase[0]:
                raise ValidationError(
                    f"{phase[1].replace('_', ' ').title()} "
                    f"starts after {next_phase[1].replace('_', ' ').title()}"
                )
            if phase[0] + timezone.timedelta(seconds=min_space) >= next_phase[0]:
                raise ValidationError(
                    f"The time between phases {phase[1].replace('_', ' ').title()} "
                    f"and {next_phase[1].replace('_', ' ').title()} is below minimum"
                )

    # --- Create-time validation + post-create / fast-forward tasks ---

    def validate_create(self) -> None:
        if self.poll.work_group_id is not None and not self.poll.poll_type == self.poll.PollType.SCORE:
            raise ValidationError("Work groups are only assignable to date polls")

    @abstractmethod
    def schedule_post_create_tasks(self) -> None: ...

    @abstractmethod
    def schedule_fast_forward_tasks(self) -> None: ...

    # --- Proposal create ---

    def create_proposal_type_data(self, proposal: PollProposal, data: dict) -> None:
        return None

    @abstractmethod
    def proposal_input_serializer_class(self) -> type[serializers.Serializer]: ...

    @abstractmethod
    def proposal_filter_class(self) -> type: ...

    def proposal_start_date(self, proposal: PollProposal) -> None:
        return None

    def proposal_end_date(self, proposal: PollProposal) -> None:
        return None

    def proposal_preliminary_score(self, proposal: PollProposal) -> None:
        return None

    # --- Vote ---

    @abstractmethod
    def vote_input_serializer_class(self) -> type[serializers.Serializer]: ...

    @abstractmethod
    def vote_output_serializer_class(self) -> type[serializers.Serializer]: ...

    @abstractmethod
    def delegate_vote_input_serializer_class(self) -> type[serializers.Serializer]: ...

    @abstractmethod
    def update_vote(self, *, group_user, data: dict) -> None: ...

    @abstractmethod
    def update_delegate_vote(self, *, delegate_pool, data: dict) -> None: ...

    @abstractmethod
    def update_vote_scores(self, *, delegate_mandate_subquery) -> None: ...

    @abstractmethod
    def vote_list_qs(self, *, fetched_by, delegates: bool, filters: dict): ...

    def on_poll_finalized(self, *, winning_proposal) -> None:
        return None


@register(Poll.PollType.SCORE)
class ScorePollType(PollType):
    def labels(self) -> tuple:
        poll = self.poll
        if poll.dynamic:
            return (
                (poll.start_date, "start_date", "dynamic"),
                (poll.end_date, "end_date", "result"),
            )

        return (
            (poll.start_date, "start_date", "area_vote"),
            (poll.area_vote_end_date, "area_vote_end_date", "proposal"),
            (poll.proposal_end_date, "proposal_end_date", "prediction_statement"),
            (
                poll.prediction_statement_end_date,
                "prediction_statement_end_date",
                "prediction_bet",
            ),
            (poll.prediction_bet_end_date, "prediction_bet_end_date", "delegate_vote"),
            (poll.delegate_vote_end_date, "delegate_vote_end_date", "vote"),
            (poll.vote_end_date, "vote_end_date", "result"),
            (poll.end_date, "end_date", "prediction_vote"),
        )

    def finished(self) -> bool:
        poll = self.poll
        now = timezone.now()
        return (poll.vote_end_date is not None and poll.vote_end_date <= now) or (
            poll.end_date is not None and poll.end_date <= now
        )

    def schedule_post_create_tasks(self) -> None:
        poll = self.poll
        _tasks.poll_area_vote_count.apply_async(
            kwargs=dict(poll_id=poll.id), eta=poll.area_vote_end_date
        )
        _tasks.poll_prediction_bet_count.apply_async(
            kwargs=dict(poll_id=poll.id), eta=poll.prediction_bet_end_date
        )

        if not poll.dynamic:
            _tasks.poll_proposal_vote_count.apply_async(
                kwargs=dict(poll_id=poll.id), eta=poll.vote_end_date
            )

    def schedule_fast_forward_tasks(self) -> None:
        poll = self.poll
        now = timezone.now()
        if poll.area_vote_end_date and poll.area_vote_end_date > now:
            _tasks.poll_area_vote_count.apply_async(
                kwargs=dict(poll_id=poll.id), eta=poll.area_vote_end_date
            )
        else:
            _tasks.poll_area_vote_count(poll_id=poll.id)

        if poll.prediction_bet_end_date and poll.prediction_bet_end_date > now:
            _tasks.poll_prediction_bet_count.apply_async(
                kwargs=dict(poll_id=poll.id), eta=poll.prediction_bet_end_date
            )
        else:
            _tasks.poll_prediction_bet_count(poll_id=poll.id)

    def proposal_input_serializer_class(self) -> type[serializers.Serializer]:
        class InputSerializerScore(
            FileCollectionCreateSerializerMixin, serializers.ModelSerializer
        ):
            class Meta:
                model = PollProposal
                fields = ("title", "description", "blockchain_id")

        return InputSerializerScore

    def proposal_filter_class(self) -> type:
        return BasePollProposalFilter

    def vote_input_serializer_class(self) -> type[serializers.Serializer]:
        class InputSerializerScore(serializers.Serializer):
            proposals = serializers.ListField(child=serializers.IntegerField())
            scores = serializers.ListField(child=serializers.IntegerField())

        return InputSerializerScore

    def vote_output_serializer_class(self) -> type[serializers.Serializer]:
        class OutputSerializerTypeScore(serializers.ModelSerializer):
            author = GroupUserSerializer(
                source="author.created_by", hide_relevant_users=True
            )

            class Meta:
                model = PollVotingTypeCardinal
                fields = ("author", "author_delegate", "proposal", "score", "raw_score")

        return OutputSerializerTypeScore

    def delegate_vote_input_serializer_class(self) -> type[serializers.Serializer]:
        return self.vote_input_serializer_class()

    @staticmethod
    def _validate_scores(scores: list[int]) -> None:
        if FLOWBACK_SCORE_VOTE_CEILING is not None and any(
            s > FLOWBACK_SCORE_VOTE_CEILING for s in scores
        ):
            raise ValidationError(
                f"Voting scores exceeds ceiling bounds (currently set at {FLOWBACK_SCORE_VOTE_CEILING})"
            )
        if FLOWBACK_SCORE_VOTE_FLOOR is not None and any(
            s < FLOWBACK_SCORE_VOTE_FLOOR for s in scores
        ):
            raise ValidationError(
                f"Voting scores exceeds floor bounds (currently set at {FLOWBACK_SCORE_VOTE_FLOOR})"
            )

    def update_vote(self, *, group_user, data: dict) -> None:
        poll = self.poll
        self._validate_scores(data["scores"])

        if not data["proposals"]:
            PollVoting.objects.filter(created_by=group_user, poll=poll).delete()
            return

        if len(data["scores"]) != len(data["proposals"]):
            raise ValidationError("The amount of votes don't match the amount of polls")

        proposals = poll.pollproposal_set.filter(id__in=data["proposals"]).all()
        if len(proposals) != len(data["proposals"]):
            raise ValidationError("Not all proposals are available to vote for")

        user_vote, _ = PollVoting.objects.get_or_create(
            created_by=group_user, poll=poll
        )
        rows = [
            PollVotingTypeCardinal(
                author=user_vote,
                proposal_id=data["proposals"][i],
                raw_score=data["scores"][i],
            )
            for i in range(len(data["proposals"]))
        ]
        PollVotingTypeCardinal.objects.filter(author=user_vote).delete()
        PollVotingTypeCardinal.objects.bulk_create(rows)

    def update_delegate_vote(self, *, delegate_pool, data: dict) -> None:
        poll = self.poll
        if not data["proposals"]:
            PollDelegateVoting.objects.filter(
                created_by=delegate_pool, poll=poll
            ).delete()
            return

        if len(data["scores"]) != len(data["proposals"]):
            raise ValidationError("The amount of votes don't match the amount of polls")

        proposals = poll.pollproposal_set.filter(id__in=data["proposals"]).all()
        if len(proposals) != len(data["proposals"]):
            raise ValidationError("Not all proposals are available to vote for")

        self._validate_scores(data["scores"])

        pool_vote, _ = PollDelegateVoting.objects.get_or_create(
            created_by=delegate_pool, poll=poll
        )
        rows = [
            PollVotingTypeCardinal(
                author_delegate=pool_vote,
                proposal_id=data["proposals"][i],
                raw_score=data["scores"][i],
            )
            for i in range(len(data["proposals"]))
        ]
        PollVotingTypeCardinal.objects.filter(author_delegate=pool_vote).delete()
        PollVotingTypeCardinal.objects.bulk_create(rows)

    def update_vote_scores(self, *, delegate_mandate_subquery) -> None:
        poll = self.poll
        PollVotingTypeCardinal.objects.filter(
            permission_q("author__created_by", "allow_vote"),
            proposal__active=True,
            author__poll=poll,
        ).update(score=F("raw_score"))

        PollVotingTypeCardinal.objects.filter(
            author_delegate__poll=poll,
            proposal__active=True,
        ).update(score=F("raw_score") * Subquery(delegate_mandate_subquery))

        proposal_scores = (
            PollVotingTypeCardinal.objects.filter(
                proposal=OuterRef("id"),
            )
            .values("proposal")
            .annotate(total_score=Sum("score"))
            .values("total_score")
        )

        PollProposal.objects.filter(poll=poll, active=True).update(
            score=Subquery(proposal_scores)
        )

    def vote_list_qs(self, *, fetched_by, delegates: bool, filters: dict):
        poll = self.poll
        group_user = group_user_permissions(
            user=fetched_by, group=poll.created_by.group.id
        )
        if delegates:
            qs = (
                PollVotingTypeCardinal.objects.filter(
                    proposal__poll=poll, author_delegate__isnull=False
                )
                .order_by("-score")
                .all()
            )
        else:
            qs = (
                PollVotingTypeCardinal.objects.filter(
                    proposal__poll=poll, author__created_by=group_user
                )
                .order_by("-score")
                .all()
            )
        return BasePollVoteCardinalFilter(filters, qs).qs


@register(Poll.PollType.V2_SCORE)
class V2ScorePollType(ScorePollType):
    def labels(self) -> tuple:
        poll = self.poll
        if poll.dynamic:
            return super().labels()

        return (
            (poll.start_date, "start_date", "proposal"),
            (poll.proposal_end_date, "proposal_end_date", "prediction_bet"),
            (poll.prediction_bet_end_date, "prediction_bet_end_date", "delegate_vote"),
            (poll.delegate_vote_end_date, "delegate_vote_end_date", "vote"),
            (poll.end_date, "end_date", "result"),
        )

    def finished(self) -> bool:
        return self.poll.end_date is not None and self.poll.end_date <= timezone.now()

    def schedule_post_create_tasks(self) -> None:
        poll = self.poll
        _tasks.poll_kpi_count.apply_async(
            kwargs=dict(poll_id=poll.id), eta=poll.prediction_bet_end_date
        )
        if not poll.dynamic:
            _tasks.poll_proposal_vote_count.apply_async(
                kwargs=dict(poll_id=poll.id), eta=poll.end_date
            )

    def schedule_fast_forward_tasks(self) -> None:
        poll = self.poll
        now = timezone.now()
        if poll.prediction_bet_end_date and poll.prediction_bet_end_date > now:
            _tasks.poll_kpi_count.apply_async(
                kwargs=dict(poll_id=poll.id), eta=poll.prediction_bet_end_date
            )
        else:
            _tasks.poll_kpi_count(poll_id=poll.id)


@register(Poll.PollType.SCHEDULE)
class SchedulePollType(PollType):
    def labels(self) -> tuple:
        poll = self.poll
        return (
            (poll.start_date, "start_date", "schedule"),
            (poll.end_date, "end_date", "result"),
        )

    def validate_create(self) -> None:
        if not self.poll.end_date:
            raise ValidationError("Missing required parameter(s) for schedule poll")
        if not self.poll.dynamic:
            raise ValidationError("Schedule poll must be dynamic")

    def schedule_post_create_tasks(self) -> None:
        poll = self.poll
        _tasks.poll_area_vote_count.apply_async(
            kwargs=dict(poll_id=poll.id), eta=poll.area_vote_end_date
        )

    def schedule_fast_forward_tasks(self) -> None:
        pass

    def create_proposal_type_data(self, proposal: PollProposal, data: dict) -> None:
        if not (data.get("start_date") and data.get("end_date")):
            raise ValidationError(
                "Missing start_date and/or end_date, for proposal schedule creation"
            )

        schedule_proposal = PollProposalTypeSchedule(
            proposal=proposal,
            event_start_date=data["start_date"],
            event_end_date=data["end_date"],
        )
        try:
            schedule_proposal.full_clean()
        except ValidationError:
            proposal.delete()
            raise

        schedule_proposal.save()

    def proposal_input_serializer_class(self) -> type[serializers.Serializer]:
        class InputSerializerSchedule(
            FileCollectionCreateSerializerMixin, serializers.ModelSerializer
        ):
            start_date = serializers.DateTimeField()
            end_date = serializers.DateTimeField()

            def validate(self, data):
                if data.get("start_date") >= data.get("end_date"):
                    raise ValidationError(
                        "Start date can't be the same or later than End date"
                    )
                return data

            class Meta:
                model = PollProposal
                fields = (
                    "title",
                    "description",
                    "blockchain_id",
                    "start_date",
                    "end_date",
                )

        return InputSerializerSchedule

    def proposal_filter_class(self) -> type:
        return BasePollProposalScheduleFilter

    def proposal_start_date(self, proposal: PollProposal):
        return proposal.pollproposaltypeschedule.event_start_date

    def proposal_end_date(self, proposal: PollProposal):
        return proposal.pollproposaltypeschedule.event_end_date

    def proposal_preliminary_score(self, proposal: PollProposal):
        return proposal.pollproposaltypeschedule.preliminary_score

    def vote_input_serializer_class(self) -> type[serializers.Serializer]:
        class InputSerializerSchedule(serializers.Serializer):
            proposals = serializers.ListField(child=serializers.IntegerField())

        return InputSerializerSchedule

    def vote_output_serializer_class(self) -> type[serializers.Serializer]:
        class OutputSerializerTypeForAgainst(serializers.ModelSerializer):
            author = GroupUserSerializer(
                source="author.created_by", hide_relevant_users=True
            )

            class Meta:
                model = PollVotingTypeForAgainst
                fields = ("author", "author_delegate", "proposal", "vote", "score")

        return OutputSerializerTypeForAgainst

    def delegate_vote_input_serializer_class(self) -> type[serializers.Serializer]:
        return self.vote_input_serializer_class()

    def update_vote(self, *, group_user, data: dict) -> None:
        poll = self.poll
        if not data["proposals"]:
            PollVoting.objects.filter(created_by=group_user, poll=poll).delete()
            return

        if len(set(data["proposals"])) != len(data["proposals"]):
            raise ValidationError("Duplicate proposals are not allowed")

        proposals = poll.pollproposal_set.filter(id__in=data["proposals"]).all()
        if len(proposals) != len(data["proposals"]):
            raise ValidationError("Not all proposals are available to vote for")

        poll_vote, _ = PollVoting.objects.get_or_create(
            created_by=group_user, poll=poll
        )
        rows = [
            PollVotingTypeForAgainst(author=poll_vote, proposal_id=proposal, vote=True)
            for proposal in data["proposals"]
        ]

        old_proposal_ids = list(
            PollVotingTypeForAgainst.objects.filter(author=poll_vote).values_list(
                "proposal_id", flat=True
            )
        )

        PollVotingTypeForAgainst.objects.filter(author=poll_vote).delete()
        PollVotingTypeForAgainst.objects.bulk_create(rows)

        PollProposalTypeSchedule.objects.filter(
            proposal_id__in=old_proposal_ids
        ).update(preliminary_score=F("preliminary_score") - 1)
        PollProposalTypeSchedule.objects.filter(
            proposal_id__in=data["proposals"]
        ).update(preliminary_score=F("preliminary_score") + 1)

    def update_delegate_vote(self, *, delegate_pool, data: dict) -> None:
        poll = self.poll
        if not data["proposals"]:
            PollDelegateVoting.objects.filter(
                created_by=delegate_pool, poll=poll
            ).delete()
            return

        proposals = poll.pollproposal_set.filter(id__in=data["proposals"]).all()
        if len(proposals) != len(data["proposals"]):
            raise ValidationError("Not all proposals are available to vote for")

        poll_vote, _ = PollDelegateVoting.objects.get_or_create(
            created_by=delegate_pool, poll=poll
        )
        rows = [
            PollVotingTypeForAgainst(
                author_delegate=poll_vote, proposal_id=proposal, vote=True
            )
            for proposal in data["proposals"]
        ]
        PollVotingTypeForAgainst.objects.filter(author_delegate=poll_vote).delete()
        PollVotingTypeForAgainst.objects.bulk_create(rows)

    def update_vote_scores(self, *, delegate_mandate_subquery) -> None:
        poll = self.poll
        PollVotingTypeForAgainst.objects.filter(
            permission_q("author__created_by", "allow_vote"),
            proposal__active=True,
            author__poll=poll,
        ).update(score=Case(When(vote=True, then=1), default=-1))

        PollVotingTypeForAgainst.objects.filter(
            author_delegate__poll=poll,
            proposal__active=True,
        ).update(
            score=Case(When(vote=True, then=1), default=-1)
            * Subquery(delegate_mandate_subquery)
        )

        proposal_scores = (
            PollVotingTypeForAgainst.objects.filter(
                proposal=OuterRef("id"),
            )
            .values("proposal")
            .annotate(total_score=Sum("score"))
            .values("total_score")
        )

        PollProposal.objects.filter(poll=poll, active=True).update(
            score=Subquery(proposal_scores)
        )

    def vote_list_qs(self, *, fetched_by, delegates: bool, filters: dict):
        poll = self.poll
        qs = (
            PollVotingTypeForAgainst.objects.filter(proposal__poll=poll)
            .order_by("-vote")
            .all()
        )
        if poll.created_by.group.hide_poll_users:
            filters["created_by_user_id"] = fetched_by.id
        return BasePollVoteForAgainstFilter(filters, qs).qs

    def on_poll_finalized(self, *, winning_proposal) -> None:
        poll = self.poll
        if poll.status != 1 or not winning_proposal:
            return
        schedule = (
            poll.created_by.group.schedule
            if poll.work_group is None
            else poll.work_group.schedule
        )
        schedule.create_event(
            title=poll.title,
            description=poll.description,
            meeting_link=poll.schedule_poll_meeting_link,
            start_date=winning_proposal.pollproposaltypeschedule.event_start_date,
            end_date=winning_proposal.pollproposaltypeschedule.event_end_date,
            created_by=poll,
        )


def _poll_pre_save(sender, instance: Poll, *args, **kwargs):
    instance.poll_type = Poll.normalize_poll_type(instance.poll_type, instance.version)
    labels = [x[1] for x in of(instance).labels()]
    for tt_entry in instance.time_table:
        if tt_entry[1] not in labels:
            setattr(instance, tt_entry[1], None)


pre_save.connect(_poll_pre_save, sender=Poll)
