
from typing import TYPE_CHECKING

from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q, F
from django.db.models.signals import post_delete
from django.utils.translation import gettext_lazy as _

from flowback.files.models import FileCollection
from flowback.notification.models import NotifiableModel, NotificationChannel
from flowback.common.models import BaseModel
from flowback.common.validators import FieldNotBlankValidator
from flowback.group.models import GroupUser, GroupTags, WorkGroup
from flowback.comment.models import CommentSection, comment_section_create_model_default

if TYPE_CHECKING:
    from flowback.poll.classes.poll_type import PollType as PollTypeNew


# Create your models here.
class Poll(BaseModel, NotifiableModel):
    # Depricated class
    class PollType(models.TextChoices):
        SCHEDULE = 'schedule', _('schedule')
        SCORE = 'score', _('score')
        V2_SCORE = 'v2_score', _('v2 score')

    poll_type = models.CharField(max_length=32, choices=PollType.choices)

    @staticmethod
    def normalize_poll_type(poll_type: str, version: int) -> str:
        if poll_type == Poll.PollType.SCORE and version == 2:
            return Poll.PollType.V2_SCORE
        return poll_type

    @property
    def poll_type_new(self) -> "PollTypeNew":
        from flowback.poll.classes.poll_type import of
        return of(self)

    created_by = models.ForeignKey(GroupUser, on_delete=models.CASCADE)

    # General information
    title = models.CharField(max_length=255, validators=[FieldNotBlankValidator])
    description = models.TextField(null=True, blank=True, validators=[FieldNotBlankValidator])
    attachments = models.ForeignKey(FileCollection, on_delete=models.SET_NULL, null=True, blank=True)
    version = models.PositiveIntegerField(default=1, validators=[MaxValueValidator(2), MinValueValidator(1)])
    quorum = models.IntegerField(default=None, null=True, blank=True,
                                 validators=[MinValueValidator(0), MaxValueValidator(100)])
    tag = models.ForeignKey(GroupTags, on_delete=models.CASCADE, null=True, blank=True)
    pinned = models.BooleanField(default=False)

    # Determines the visibility of this poll
    active = models.BooleanField(default=True)

    # Determines if poll is visible outside of group
    public = models.BooleanField(default=False)
    allow_fast_forward = models.BooleanField(default=False)
    interval_mean_absolute_correctness = models.DecimalField(
        max_digits=12,
        decimal_places=9,
        null=True,
        blank=True,
        help_text="Calculates after end date, will contain the current Interval Mean Absolute Correctness "
                  "at the time of calculation.")

    # Poll Phases
    start_date = models.DateTimeField()  # Poll Start
    area_vote_end_date = models.DateTimeField(null=True, blank=True)  # Area Selection Phase
    proposal_end_date = models.DateTimeField(null=True, blank=True)  # Proposal Phase
    prediction_statement_end_date = models.DateTimeField(null=True, blank=True)  # Prediction Phase
    prediction_bet_end_date = models.DateTimeField(null=True, blank=True)  # Prediction Betting Phase
    delegate_vote_end_date = models.DateTimeField(null=True, blank=True)  # Delegate Voting Phase
    vote_end_date = models.DateTimeField(null=True, blank=True)  # Voting Phase
    end_date = models.DateTimeField()  # Result Phase, Prediction Vote afterward indefinitely

    blockchain_id = models.PositiveIntegerField(null=True, blank=True, default=None)
    work_group = models.ForeignKey(WorkGroup, on_delete=models.CASCADE, null=True, blank=True)
    schedule_poll_meeting_link = models.URLField(null=True, blank=True)

    """
    Poll Status Code
    0 - Ongoing
    1 - Finished
    -1 - Failed Quorum
    """
    status = models.IntegerField(default=0)

    """
    Prediction Status Code
    0 - Idle
    1 - Finished
    2 - Calculating Combined Bets
    """
    status_prediction = models.IntegerField(default=0)
    result = models.ForeignKey('poll.PollProposal', null=True, blank=True, on_delete=models.SET_NULL,
                               related_name='winning_proposal')

    # Comment section
    comment_section = models.ForeignKey(CommentSection, default=comment_section_create_model_default,
                                        on_delete=models.DO_NOTHING)

    # Optional dynamic counting support
    participants = models.IntegerField(default=0)
    dynamic = models.BooleanField()

    def clean(self):
        self.poll_type_new.validate_create()
        self.poll_type_new.validate_phases()

        super().clean()

    @property
    def group(self):
        return self.created_by.group

    @property
    def finished(self):
        return self.poll_type_new.finished()

    @property
    def labels(self) -> tuple:
        return self.poll_type_new.labels()

    @property
    def current_phase(self) -> str:
        return self.poll_type_new.current_phase()

    @property
    def time_table(self) -> list:
        return [[self.start_date, 'start_date', 'area_vote'],
                [self.area_vote_end_date, 'area_vote_end_date', 'proposal'],
                [self.proposal_end_date, 'proposal_end_date', 'prediction_statement'],
                [self.prediction_statement_end_date, 'prediction_statement_end_date', 'prediction_bet'],
                [self.prediction_bet_end_date, 'prediction_bet_end_date', 'delegate_vote'],
                [self.delegate_vote_end_date, 'delegate_vote_end_date', 'vote'],
                [self.vote_end_date, 'vote_end_date', 'result'],
                [self.end_date, 'end_date', 'prediction_vote']]

    def get_phase(self, phase: str, use_time_table: bool = False, field_name: bool = False):
        return self.poll_type_new.get_phase(phase, use_time_table=use_time_table, field_name=field_name)

    def phase_exist(self, phase: str, raise_exception: bool = True) -> bool:
        return self.poll_type_new.phase_exist(phase, raise_exception=raise_exception)

    def check_phase(self, *phases: str, raise_exception: bool = True) -> bool:
        return self.poll_type_new.check_phase(*phases, raise_exception=raise_exception)

    class Meta:
        constraints = [models.CheckConstraint(check=Q(Q(area_vote_end_date__isnull=True)
                                                      | Q(area_vote_end_date__gte=F('start_date'))),
                                              name='areavoteenddategreaterthanstartdate_check'),
                       models.CheckConstraint(check=Q(Q(proposal_end_date__isnull=True)
                                                      | Q(proposal_end_date__gte=F('area_vote_end_date'))),
                                              name='proposalenddategreaterthanareavoteenddate_check'),
                       models.CheckConstraint(check=Q(Q(prediction_statement_end_date__isnull=True)
                                                      | Q(prediction_statement_end_date__gte=F('proposal_end_date'))),
                                              name='predictionstatementenddategreaterthanproposalenddate_check'),
                       models.CheckConstraint(check=Q(Q(prediction_bet_end_date__isnull=True)
                                                      | Q(
                           prediction_bet_end_date__gte=F('prediction_statement_end_date'))),
                                              name='predictionbetenddategreaterthanpredictionstatementeneddate_check'),
                       models.CheckConstraint(check=Q(Q(delegate_vote_end_date__isnull=True)
                                                      | Q(delegate_vote_end_date__gte=F('prediction_bet_end_date'))),
                                              name='delegatevoteenddategreaterthanpredictionbetenddate_check'),
                       models.CheckConstraint(check=Q(Q(vote_end_date__isnull=True)
                                                      | Q(vote_end_date__gte=F('delegate_vote_end_date'))),
                                              name='voteenddategreaterthandelegatevoteenddate_check'),
                       models.CheckConstraint(check=Q(Q(end_date__isnull=True)
                                                      | Q(end_date__gte=F('vote_end_date'))),
                                              name='enddategreaterthanvoteenddate_check'),

                       models.CheckConstraint(check=~Q(Q(poll_type='schedule') & Q(dynamic=False)),
                                              name='polltypeisscheduleanddynamic_check')]

    NOTIFICATION_DATA_FIELDS = (('poll_id', int),
                                ('poll_title', str),
                                ('group_id', int),
                                ('group_name', str),
                                ('group_image', str, 'The URL path to the image of the group'))

    # Notification
    @property
    def notification_data(self) -> dict | None:
        return dict(poll_id=self.id,
                    poll_title=self.title,
                    group_id=self.created_by.group.id,
                    group_name=self.created_by.group.name,
                    group_image=self.created_by.group.image)

    def notify_poll(self,
                    action: NotificationChannel.Action,
                    message: str,
                    work_group_id: int,
                    work_group_name: str,
                    subscription_filters: dict):
        """
        Notifies when a poll updates and deletes.
        Also notifies when poll area, prediction and proposal votes have been counted.
        :param action:
        :param message:
        :param work_group_id:
        :param work_group_name:
        :param subscription_filters:
        :return:
        """
        params = locals()
        params.pop('self')

        return self.notification_channel.notify(**params)

    def notify_poll_phase(self,
                          action: NotificationChannel.Action,
                          message: str,
                          work_group_id: int,
                          work_group_name: str,
                          current_phase: str,
                          subscription_filters: dict):
        """
        Notifies when a poll does fast-forward
        """
        params = locals()
        params.pop('self')

        return self.notification_channel.notify(**params)

    def notify_poll_comment(self,
                            action: NotificationChannel.Action,
                            message: str,
                            work_group_id: int,
                            work_group_name: str,
                            subscription_filters: dict,
                            exclude_subscription_filters: dict,
                            comment_message: str):
        """
        Notifies about new comments
        """
        params = locals()
        params.pop('self')

        return self.notification_channel.notify(**params)

    @classmethod
    def post_delete(cls, instance, **kwargs):
        if hasattr(instance, 'schedule'):
            instance.schedule.delete()


post_delete.connect(Poll.post_delete, sender=Poll)
