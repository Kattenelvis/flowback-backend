from rest_framework.test import APITestCase

from flowback.common.tests import generate_request
from flowback.group.models import GroupKPI, GroupUser, Group, GroupKPIValue
from flowback.group.tests.factories import GroupFactory, GroupUserFactory, GroupKPIFactory, GroupKPIValueFactory
from flowback.poll.models import PollProposalKPIVote, PollProposalKPIBet, Poll, PollProposalKPI, PollProposal
from flowback.poll.tasks import poll_kpi_count
from flowback.poll.tests.factories import PollFactory, PollProposalFactory, PollProposalKPIBetFactory, \
    PollProposalKPIVoteFactory
from flowback.poll.tests.utils import generate_poll_phase_kwargs
from flowback.poll.views.prediction import PollProposalKPIBetAPI, PollProposalKPIVoteAPI, PollProposalKPIBetListAPI, \
    PollProposalKPIVoteListAPI
from flowback.poll.views.proposal import PollProposalCreateAPI


class TestPollProposalKPI(APITestCase):
    def setUp(self):
        self.group = GroupFactory()
        self.group_user_creator = self.group.group_user_creator
        self.group_kpi_one, self.group_kpi_two, self.group_kpi_three = GroupKPIFactory.create_batch(3, group=self.group)
        [GroupKPIValueFactory(kpi=self.group_kpi_one, value=i) for i in [12, 22, 29]]
        [GroupKPIValueFactory(kpi=self.group_kpi_two, value=i) for i in [19, 99, 218, 227, 310, 827]]
        [GroupKPIValueFactory(kpi=self.group_kpi_three, value=i) for i in [12, 127, 198]]

        self.group_user_one, self.group_user_two = GroupUserFactory.create_batch(2, group=self.group)
        self.poll = PollFactory(created_by=self.group_user_creator,
                                poll_type=4,
                                version=2,
                                **generate_poll_phase_kwargs('prediction_bet'))

        self.proposal_one, self.proposal_two, self.proposal_three = PollProposalFactory.create_batch(3,
                                                                                                     poll=self.poll,
                                                                                                     created_by=self.group_user_one)

    def test_proposal_create_kpi(self):
        Poll.objects.filter(id=self.poll.id).update(**generate_poll_phase_kwargs('proposal'))
        self.assertEqual(PollProposalKPI.objects.all().count(), 36)

        response = generate_request(api=PollProposalCreateAPI,
                                    user=self.group_user_one.user,
                                    url_params=dict(poll=self.poll.id),
                                    data=dict(title="hi", description="there"))

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(PollProposalKPI.objects.all().count(), 48)

    def test_kpi_bet(self):
        values = [12, 22, 29]
        weights = [19, 705, 2]

        response = generate_request(api=PollProposalKPIBetAPI,
                                    user=self.group_user_one.user,
                                    url_params=dict(proposal_id=self.proposal_one.id),
                                    data=dict(kpi_id=self.group_kpi_one.id,
                                              values=values,
                                              weights=weights))

        self.assertEqual(response.status_code, 200, response.data)

        for i in range(3):
            self.assertTrue(PollProposalKPIBet.objects.filter(created_by=self.group_user_one,
                                                              proposal_kpi__kpi_value__value=values[i],
                                                              weight=weights[i]).exists(),
                            f"KPI bet with value {values[i]} and weight {weights[i]} does not exist!")

    def test_kpi_vote(self):
        bets = [(self.group_kpi_one, 12), (self.group_kpi_one, 22), (self.group_kpi_two, 99)]
        for i in range(3):
            PollProposalKPIBetFactory(created_by=self.group_user_one,
                                      proposal_kpi=PollProposalKPI.objects.get(proposal=self.proposal_one,
                                                                               kpi_value__kpi=bets[i][0],
                                                                               kpi_value__value=bets[i][1]))

        Poll.objects.filter(id=self.poll.id).update(**generate_poll_phase_kwargs('prediction_vote'))
        response = generate_request(api=PollProposalKPIVoteAPI,
                                    user=self.group_user_two.user,
                                    url_params=dict(proposal_id=self.proposal_one.id),
                                    data=dict(kpi_id=self.group_kpi_one.id,
                                              vote=22))

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(PollProposalKPIVote.objects.filter(created_by=self.group_user_two,
                                                           proposal_kpi__kpi_value__value=22).exists())

    def generate_kpi_poll(self, group: Group) -> Poll:
        poll = PollFactory(created_by=group.group_user_creator,
                           poll_type=4,
                           version=2,
                           **generate_poll_phase_kwargs('prediction_bet'))

        return poll

    def generate_kpi_bet(self,
                         group_user: GroupUser,
                         group_kpi: GroupKPI,
                         proposal: PollProposal,
                         value: int,
                         weight: int) -> PollProposal:

        PollProposalKPIBetFactory(created_by=group_user,
                                  weight=weight,
                                  proposal_kpi=PollProposalKPI.objects.get(proposal=proposal,
                                                                           kpi_value__kpi=group_kpi,
                                                                           kpi_value__value=value))

        return proposal


    def generate_kpi_vote(self, group_user: GroupUser, group_kpi: GroupKPI, proposal: PollProposal, value: int):
        return PollProposalKPIVoteFactory(created_by=group_user,
                                          proposal_kpi=PollProposalKPI.objects.get(proposal=proposal,
                                                                                   kpi_value__kpi=group_kpi,
                                                                                   kpi_value__value=value))


    def test_kpi_combined_bet(self):
        # group_kpi_one, [12, 22, 29]
        # group_kpi_two, [19, 99, 218, 227, 310, 827]
        # group_kpi_three, [12, 127, 198, 228]

        # Poll one
        poll_one = self.generate_kpi_poll(group=self.group)
        proposal_one = PollProposalFactory(poll=poll_one, created_by=self.group_user_creator)

        self.generate_kpi_bet(self.group_user_one, self.group_kpi_one, proposal_one, 22, 10)
        self.generate_kpi_bet(self.group_user_two, self.group_kpi_one, proposal_one, 22, 10)
        self.generate_kpi_bet(self.group_user_two, self.group_kpi_one, proposal_one, 12, 16)
        Poll.objects.filter(id=poll_one.id).update(**generate_poll_phase_kwargs('prediction_vote'))
        poll_kpi_count(poll_id=poll_one.id)

        print("Winner: ", PollProposalKPI.objects.get(proposal=proposal_one,
                                                      kpi_value__kpi=self.group_kpi_one,
                                                      kpi_value__value=22).kpi_value_id)

        self.generate_kpi_vote(self.group_user_two, self.group_kpi_one, proposal_one, 22)

        # Poll two
        poll_two = self.generate_kpi_poll(group=self.group)
        proposal_two = PollProposalFactory(poll=poll_two, created_by=self.group_user_creator)

        self.generate_kpi_bet(self.group_user_one, self.group_kpi_one, proposal_two, 22, 22)
        self.generate_kpi_bet(self.group_user_two, self.group_kpi_one, proposal_two, 22, 12)
        self.generate_kpi_bet(self.group_user_one, self.group_kpi_one, proposal_two, 12, 16)
        Poll.objects.filter(id=poll_two.id).update(**generate_poll_phase_kwargs('prediction_vote'))
        poll_kpi_count(poll_id=poll_two.id)

        print("Winner: ", PollProposalKPI.objects.get(proposal=proposal_two,
                                                      kpi_value__kpi=self.group_kpi_one,
                                                      kpi_value__value=12).kpi_value_id)

        self.generate_kpi_vote(self.group_user_two, self.group_kpi_one, proposal_two, 12)

        # Poll three
        poll_three = self.generate_kpi_poll(group=self.group)
        proposal_three = PollProposalFactory(poll=poll_three, created_by=self.group_user_creator)

        self.generate_kpi_bet(self.group_user_one, self.group_kpi_one, proposal_three, 22, 22)
        self.generate_kpi_bet(self.group_user_two, self.group_kpi_two, proposal_three, 227, 12)
        self.generate_kpi_bet(self.group_user_one, self.group_kpi_two, proposal_three, 227, 16)
        Poll.objects.filter(id=poll_three.id).update(**generate_poll_phase_kwargs('prediction_vote'))
        poll_kpi_count(poll_id=poll_three.id)

        print("Winner: ", PollProposalKPI.objects.get(proposal=proposal_three,
                                                      kpi_value__kpi=self.group_kpi_two,
                                                      kpi_value__value=227).kpi_value_id)

        self.generate_kpi_vote(self.group_user_two, self.group_kpi_one, proposal_three, 22)

        # Poll four
        poll_four = self.generate_kpi_poll(group=self.group)
        proposal_four = PollProposalFactory(poll=poll_four, created_by=self.group_user_creator)

        self.generate_kpi_bet(self.group_user_one, self.group_kpi_one, proposal_four, 22, 22)
        self.generate_kpi_bet(self.group_user_two, self.group_kpi_one, proposal_four, 22, 12)
        self.generate_kpi_bet(self.group_user_two, self.group_kpi_one, proposal_four, 12, 16)

        poll_kpi_count(poll_id=poll_four.id)


    def test_proposal_kpi_list(self):
        response = generate_request


    def test_kpi_bet_list(self):
        [PollProposalKPIBetFactory(proposal_kpi=PollProposalKPI.objects.get(proposal=self.proposal_one,
                                                                            kpi_value__kpi=self.group_kpi_one,
                                                                            kpi_value__value=i),
                                   created_by=self.group_user_one) for i in [12, 22, 29]]

        response = generate_request(api=PollProposalKPIBetListAPI,
                                    user=self.group_user_one.user,
                                    data=dict(kpi_ids=f'{self.group_kpi_one.id}'),
                                    url_params=dict(group_id=self.group.id))

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['count'], 3)


    def test_kpi_vote_list(self):
        for i in [12, 22, 29]:
            PollProposalKPIBetFactory(proposal_kpi=PollProposalKPI.objects.get(proposal=self.proposal_one,
                                                                               kpi_value__kpi=self.group_kpi_one,
                                                                               kpi_value__value=i),
                                      created_by=self.group_user_one)

        Poll.objects.filter(id=self.poll.id).update(**generate_poll_phase_kwargs('prediction_vote'))

        PollProposalKPIVote.objects.create(created_by=self.group_user_two,
                                           proposal_kpi=PollProposalKPI.objects.get(proposal=self.proposal_one,
                                                                                    kpi_value__value=22))

        response = generate_request(api=PollProposalKPIVoteListAPI,
                                    user=self.group_user_two.user,
                                    url_params=dict(group_id=self.group.id))

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['count'], 1)
