from datetime import timedelta

from flowback.common.tests import generate_request
from flowback.poll.views.poll import PollListApi
from flowback.poll.views.vote import PollProposalVoteUpdateAPI
from flowback.user.models import User
import time_machine
from django.utils import timezone
from rest_framework.test import APITestCase

from flowback.group.models import GroupUser
from flowback.group.tests.factories import GroupFactory, GroupUserFactory
from flowback.notification.models import NotificationObject
from flowback.poll.models import Poll, PollProposal
from flowback.poll.tasks import poll_proposal_vote_count
from flowback.poll.tests.factories import (
    PollFactory,
    PollProposalFactory,
    PollVotingFactory,
    PollVotingTypeForAgainstFactory,
)
from flowback.poll.tests.utils import generate_poll_phase_kwargs
from flowback.schedule.models import ScheduleEvent


class DatePollScheduleNotificationTest(APITestCase):
    def setUp(self):
        self.group = GroupFactory()
        self.creator = GroupUser.objects.get(
            user=self.group.created_by, group=self.group
        )
        self.voter = GroupUserFactory(group=self.group)

    @staticmethod
    def schedule_vote_update(user: User, poll: Poll, proposals: list[PollProposal]):
        data = dict(proposals=[x.id for x in proposals])
        return generate_request(
            api=PollProposalVoteUpdateAPI,
            data=data,
            url_params={"poll": poll.id},
            user=user,
        )

    def test_schedule_poll_creates_notification_at_event_start(self):
        # Create a SCHEDULE poll where voting has just ended
        poll = PollFactory(
            created_by=self.creator,
            poll_type=Poll.PollType.SCHEDULE,
            dynamic=True,
            **generate_poll_phase_kwargs("vote"),
        )

        # PollProposalFactory auto-creates PollProposalTypeSchedule for SCHEDULE polls
        proposal = PollProposalFactory(poll=poll, created_by=self.voter)
        event_start = proposal.pollproposaltypeschedule.event_start_date

        response = self.schedule_vote_update(self.creator.user, poll, [proposal])

        # Cast a vote for the proposal so it wins
        poll_voting = PollVotingFactory(poll=poll, created_by=self.voter)
        PollVotingTypeForAgainstFactory(
            author=poll_voting, proposal=proposal, vote=True
        )

        # Finalize the poll — creates a ScheduleEvent on the group's schedule
        poll_proposal_vote_count(poll_id=poll.id)

        poll.refresh_from_db()

        events = ScheduleEvent.objects.filter(schedule=self.group.schedule)
        print(events.first().start_date, event_start, "ALL EVENTS")

        event = ScheduleEvent.objects.filter(schedule=self.group.schedule).first()
        self.assertIsNotNone(
            event, "A ScheduleEvent should be created after poll completion"
        )
        self.assertEqual(event.start_date, event_start)

        list_response = generate_request(
            api=PollListApi,
            data=dict(id=poll.id),
            user=self.creator.user,
            url_params=dict(group_id=self.group.id),
        )

        print(list_response.data["results"][0], "LIST")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.data["count"], 1)

        # Build timed notification objects for the event's start date
        event.regenerate_notifications()

        start_notification = NotificationObject.objects.filter(
            channel=event.notification_channel,
            tag="start",
        ).first()
        self.assertIsNotNone(
            start_notification,
            "A 'start' NotificationObject should exist for the event",
        )
        self.assertEqual(start_notification.timestamp, event_start)

        # At event start time the notification timestamp should be <= now
        with time_machine.travel(event_start + timedelta(seconds=1)):
            self.assertLessEqual(start_notification.timestamp, timezone.now())
