from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q, Count
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import ValidationError

from backend.settings import FLOWBACK_SCORE_VOTE_CEILING, FLOWBACK_SCORE_VOTE_FLOOR
from flowback.files.models import FileCollection
from flowback.prediction.models import (PredictionBet,
                                        PredictionStatement,
                                        PredictionStatementSegment,
                                        PredictionStatementVote)
from flowback.common.models import BaseModel
from flowback.common.validators import FieldNotBlankValidator
from flowback.group.models import GroupUser, GroupUserDelegatePool, GroupTags, GroupKPIValue
from flowback.poll.models import Poll
import pgtrigger


class PollProposal(BaseModel):
    created_by = models.ForeignKey(GroupUser, on_delete=models.CASCADE)
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE)

    title = models.CharField(max_length=255, null=True, blank=True, validators=[FieldNotBlankValidator])
    description = models.TextField(null=True, blank=True, validators=[FieldNotBlankValidator])
    attachments = models.ForeignKey(FileCollection, on_delete=models.CASCADE, null=True, blank=True)
    score = models.IntegerField(null=True, blank=True)
    blockchain_id = models.PositiveIntegerField(null=True, blank=True, default=None)

    active = models.BooleanField(default=True)


class PollProposalTypeSchedule(BaseModel):
    proposal = models.OneToOneField(PollProposal, on_delete=models.CASCADE)
    event_start_date = models.DateTimeField()
    event_end_date = models.DateTimeField()
    preliminary_score = models.IntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['proposal', 'event_start_date', 'event_end_date'],
                                               name='unique_proposaltypeschedule')]


class PollVoting(BaseModel):
    created_by = models.ForeignKey(GroupUser, on_delete=models.CASCADE)
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('created_by', 'poll')


class PollDelegateVoting(BaseModel):
    created_by = models.ForeignKey(GroupUserDelegatePool, on_delete=models.CASCADE)
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE)
    mandate = models.IntegerField(default=0)

    class Meta:
        unique_together = ('created_by', 'poll')


class PollVotingTypeCardinal(BaseModel):
    author = models.ForeignKey(PollVoting, null=True, blank=True, on_delete=models.CASCADE)
    author_delegate = models.ForeignKey(PollDelegateVoting, null=True, blank=True, on_delete=models.CASCADE)

    proposal = models.ForeignKey(PollProposal, on_delete=models.CASCADE)
    raw_score = models.IntegerField(default=0)  # Raw vote score
    score = models.IntegerField(null=True, blank=True)

    def clean(self):
        if FLOWBACK_SCORE_VOTE_CEILING is not None and self.raw_score >= FLOWBACK_SCORE_VOTE_CEILING:
            raise ValidationError(
                f'Voting scores exceeds ceiling bounds (currently set at {FLOWBACK_SCORE_VOTE_CEILING})')

        if FLOWBACK_SCORE_VOTE_FLOOR is not None and self.raw_score <= FLOWBACK_SCORE_VOTE_FLOOR:
            raise ValidationError(f'Voting scores exceeds floor bounds (currently set at {FLOWBACK_SCORE_VOTE_FLOOR})')

    class Meta:
        unique_together = (('author', 'proposal'), ('author_delegate', 'proposal'))

        # Either author or author_delegate can be assigned, not both.

        triggers = [
            pgtrigger.Protect(
                name='protects_author_or_author_delegate',
                operation=pgtrigger.Insert | pgtrigger.Update,
                condition=(pgtrigger.Q(new__author__isnull=True, new__author_delegate__isnull=True)
                           | pgtrigger.Q(new__author__isnull=False, new__author_delegate__isnull=False))
            )
        ]


class PollVotingTypeForAgainst(BaseModel):
    author = models.ForeignKey(PollVoting, null=True, blank=True, on_delete=models.CASCADE)
    author_delegate = models.ForeignKey(PollDelegateVoting, null=True, blank=True, on_delete=models.CASCADE)

    proposal = models.ForeignKey(PollProposal, on_delete=models.CASCADE)
    vote = models.BooleanField()  # Raw vote score, 0 = Against, 1 = For
    score = models.IntegerField(default=0)  # Calculated vote score (delegate only)

    class Meta:
        unique_together = (('author', 'proposal'), ('author_delegate', 'proposal'))

        # Either author or author_delegate can be assigned, not both.

        triggers = [
            pgtrigger.Protect(
                name='protects_author_or_author_delegate',
                operation=pgtrigger.Insert | pgtrigger.Update,
                condition=(pgtrigger.Q(new__author__isnull=True, new__author_delegate__isnull=True)
                           | pgtrigger.Q(new__author__isnull=False, new__author_delegate__isnull=False))
            )
        ]


# TODO Area requires refactor
class PollAreaStatement(BaseModel):
    created_by = models.ForeignKey(GroupUser, on_delete=models.CASCADE)
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE)


class PollAreaStatementSegment(BaseModel):
    poll_area_statement = models.ForeignKey(PollAreaStatement, on_delete=models.CASCADE)
    tag = models.ForeignKey(GroupTags, on_delete=models.CASCADE)

    def clean(self):
        if self.tag.active is False:
            raise ValidationError("Tag must be active")


class PollAreaStatementVote(BaseModel):
    created_by = models.ForeignKey(GroupUser, on_delete=models.CASCADE)
    poll_area_statement = models.ForeignKey(PollAreaStatement, on_delete=models.CASCADE)
    vote = models.BooleanField()

    class Meta:
        unique_together = ('created_by', 'poll_area_statement')


class PollPredictionStatement(PredictionStatement):
    created_by = models.ForeignKey(GroupUser, on_delete=models.CASCADE)
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE)

    def clean(self):
        if self.poll.end_date > self.end_date:
            raise ValidationError('Poll ends later than prediction statement deadline')

    @receiver(post_delete, sender=PollProposal)
    def clean_prediction_statement(sender, instance: PollProposal, **kwargs):
        PollPredictionStatement.objects.filter(poll=instance.poll) \
            .annotate(segment_count=Count('pollpredictionstatementsegment')) \
            .filter(segment_count__lt=1) \
            .delete()


class PollPredictionStatementSegment(PredictionStatementSegment):
    prediction_statement = models.ForeignKey(PollPredictionStatement, on_delete=models.CASCADE)
    proposal = models.ForeignKey(PollProposal, on_delete=models.CASCADE)


class PollPredictionStatementVote(PredictionStatementVote):
    prediction_statement = models.ForeignKey(PollPredictionStatement, on_delete=models.CASCADE)
    created_by = models.ForeignKey(GroupUser, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('prediction_statement', 'created_by')


class PollPredictionBet(PredictionBet):
    prediction_statement = models.ForeignKey(PollPredictionStatement, on_delete=models.CASCADE)
    created_by = models.ForeignKey(GroupUser, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('prediction_statement', 'created_by')

    @receiver(post_save, sender=PredictionStatement)
    def reset_prediction_prediction(sender, instance: PredictionStatement, **kwargs):
        PollPredictionBet.objects.filter(prediction_statement=instance).delete()

    @receiver(post_save, sender=PollProposal)
    def reset_prediction_proposal(sender, instance: PollProposal, **kwargs):
        PollPredictionBet.objects.filter(
            prediction_statement__pollpredictionstatementsegment__proposal=instance).delete()


class PollProposalKPI(BaseModel):
    proposal = models.ForeignKey(PollProposal, on_delete=models.CASCADE)
    kpi_value = models.ForeignKey('group.GroupKPIValue', on_delete=models.CASCADE)
    combined_bet = models.DecimalField(max_digits=8, decimal_places=7, null=True, blank=True)

    @classmethod
    def generate_kpis(self, proposal_id: int) -> None:
        """
        Generates KPI's for a poll proposal
        :param proposal_id: The ID of the proposal
        :return: None
        """
        proposal = PollProposal.objects.get(id=proposal_id)
        proposal_kpi = list(
            PollProposalKPI.objects.filter(proposal_id=proposal_id).values_list('kpi_value_id', flat=True))
        kpi_values = GroupKPIValue.objects.filter(kpi__group=proposal.poll.created_by.group,
                                                  kpi__active=True).exclude(id__in=proposal_kpi)

        data = [PollProposalKPI(proposal_id=proposal_id, kpi_value=i) for i in kpi_values]
        PollProposalKPI.objects.bulk_create(data)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['proposal', 'kpi_value'], name='unique_pollproposalkpi')]


class PollProposalKPIBet(BaseModel):
    created_by = models.ForeignKey(GroupUser, on_delete=models.CASCADE)
    proposal_kpi = models.ForeignKey(PollProposalKPI, on_delete=models.CASCADE)
    weight = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    @property
    def proposal(self):
        return self.proposal_kpi.proposal

    @property
    def kpi(self):
        return self.proposal_kpi.kpi_value.kpi

    @property
    def kpi_value(self):
        return self.proposal_kpi.kpi_value

    def clean(self):
        if not self.proposal_kpi.kpi_value.kpi.active:
            raise ValidationError("KPI must be active")

    class Meta:
        constraints = [models.UniqueConstraint(fields=['created_by', 'proposal_kpi'],
                                               name='unique_pollproposalkpibet')]


class PollProposalKPIVote(BaseModel):
    created_by = models.ForeignKey(GroupUser, on_delete=models.CASCADE)
    proposal_kpi = models.ForeignKey(PollProposalKPI, on_delete=models.CASCADE)

    def clean(self):
        if not self.proposal_kpi.kpi_value.kpi.active:
            raise ValidationError("KPI must be active")

        if PollProposalKPIVote.objects.filter(proposal_kpi__proposal_id=self.proposal_kpi.proposal.id,
                                              proposal_kpi__kpi_value__kpi=self.proposal_kpi.kpi_value.kpi).exclude(pk=self.pk).exists():
            raise ValidationError("Unable to cast KPI vote on the same KPI more than once")

    class Meta:
        constraints = [models.UniqueConstraint(fields=['created_by', 'proposal_kpi'],
                                               name='unique_pollproposalkpivote')]


class PollPhaseTemplate(BaseModel):
    created_by_group_user = models.ForeignKey(GroupUser, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, validators=[FieldNotBlankValidator])
    poll_type = models.CharField(max_length=32, choices=Poll.PollType.choices)
    poll_is_dynamic = models.BooleanField(default=False)

    # We store integers that define seconds since previous phase in seconds
    # Assume area_vote_time_delta is time since poll start_date
    area_vote_time_delta = models.IntegerField(null=True, blank=True)  # Area Vote Phase
    proposal_time_delta = models.IntegerField(null=True, blank=True)  # Proposal Phase
    prediction_statement_time_delta = models.IntegerField(null=True, blank=True)  # Prediction Phase
    prediction_bet_time_delta = models.IntegerField(null=True, blank=True)  # Prediction Bet Phase
    delegate_vote_time_delta = models.IntegerField(null=True, blank=True)  # Delegate Vote Phase
    vote_time_delta = models.IntegerField(null=True, blank=True)  # Vote Phase
    end_time_delta = models.IntegerField()  # Result Phase

    class Meta:
        constraints = [
            # Check if score polls that aren't dynamic don't have any null values
            models.CheckConstraint(check=~Q(Q(Q(poll_type=Poll.PollType.SCORE) & Q(poll_is_dynamic=False))
                                            & ~Q(Q(area_vote_time_delta__isnull=False)
                                                 | Q(proposal_time_delta__isnull=False)
                                                 | Q(prediction_statement_time_delta__isnull=False)
                                                 | Q(prediction_bet_time_delta__isnull=False)
                                                 | Q(delegate_vote_time_delta__isnull=False)
                                                 | Q(vote_time_delta__isnull=False)
                                                 | Q(end_time_delta__isnull=False))),
                                   name='pollphasetemplatescoreisvalid_check'),

            # Check if v2 score polls have the reduced set of required phases
            models.CheckConstraint(check=~Q(Q(Q(poll_type=Poll.PollType.V2_SCORE) & Q(poll_is_dynamic=False))
                                            & Q(Q(area_vote_time_delta__isnull=False)
                                                | Q(prediction_statement_time_delta__isnull=False)
                                                | Q(vote_time_delta__isnull=False)
                                                | Q(proposal_time_delta__isnull=True)
                                                | Q(prediction_bet_time_delta__isnull=True)
                                                | Q(delegate_vote_time_delta__isnull=True)
                                                | Q(end_time_delta__isnull=True))),
                                   name='pollphasetemplatev2scoreisvalid_check'),

            # Check if schedule poll or dynamic poll have null values except for vote_time_delta and end_time_delta
            models.CheckConstraint(check=~Q(Q(Q(poll_type=Poll.PollType.SCHEDULE) | Q(poll_is_dynamic=True))
                                            & Q(Q(area_vote_time_delta__isnull=True)
                                                | Q(proposal_time_delta__isnull=True)
                                                | Q(prediction_statement_time_delta__isnull=True)
                                                | Q(prediction_bet_time_delta__isnull=True)
                                                | Q(delegate_vote_time_delta__isnull=True)
                                                | Q(vote_time_delta__isnull=False)
                                                | Q(end_time_delta__isnull=False))),
                                   name='pollphasetemplatescheduleordynamicisvalid_check')
        ]
