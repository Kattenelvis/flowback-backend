from rest_framework.test import APITestCase

from flowback.common.tests import generate_request
from flowback.group.models import GroupKPIValue
from flowback.group.tests.factories import GroupFactory, GroupUserFactory, GroupKPIFactory, GroupKPIValueFactory
from flowback.poll.models import PollProposalKPIVote, PollProposalKPIBet, Poll
from flowback.poll.tests.factories import PollFactory, PollProposalFactory, PollProposalKPIBetFactory
from flowback.poll.tests.utils import generate_poll_phase_kwargs
from flowback.poll.views.prediction import PollProposalKPIBetAPI, PollProposalKPIVoteAPI, PollProposalKPIBetListAPI, \
    PollProposalKPIVoteListAPI


class TestPollProposalKPI(APITestCase):
    def setUp(self):
        self.group = GroupFactory()
        self.group_user_creator = self.group.group_user_creator
        self.group_kpi_one = GroupKPIFactory(group=self.group)
        self.group_kpi_two = GroupKPIFactory(group=self.group)
        [GroupKPIValueFactory(kpi=self.group_kpi_one, value=i) for i in [12, 22, 29]]
        [GroupKPIValueFactory(kpi=self.group_kpi_two, value=i) for i in [19, 99, 218]]

        self.group_user_one, self.group_user_two = GroupUserFactory.create_batch(2, group=self.group)
        self.poll = PollFactory(created_by=self.group_user_creator,
                                poll_type=4,
                                version=2,
                                **generate_poll_phase_kwargs('prediction_bet'))

        self.proposal_one, self.proposal_two, self.proposal_three = PollProposalFactory.create_batch(3,
                                                                                                     poll=self.poll,
                                                                                                     created_by=self.group_user_one)

    def test_kpi_bet(self):
        values = [12, 22, 29]
        weights = [19, 70, 2]

        response = generate_request(api=PollProposalKPIBetAPI,
                                    user=self.group_user_one.user,
                                    url_params=dict(proposal_id=self.proposal_one.id),
                                    data=dict(kpi_id=self.group_kpi_one.id,
                                              values=values,
                                              weights=weights))

        self.assertEqual(response.status_code, 200, response.data)

        for i in range(3):
            self.assertTrue(PollProposalKPIBet.objects.filter(created_by=self.group_user_one,
                                                              kpi_value__value=values[i],
                                                              weight=weights[i]).exists(),
                            f"KPI bet with value {values[i]} and weight {weights[i]} does not exist!")

    def test_kpi_vote(self):
        bets = [(self.group_kpi_one, 12), (self.group_kpi_one, 22), (self.group_kpi_two, 99)]
        for i in range(3):
            PollProposalKPIBetFactory(created_by=self.group_user_one,
                                      proposal=self.proposal_one,
                                      kpi_value=GroupKPIValue.objects.get(kpi=bets[i][0], value=bets[i][1]))

        Poll.objects.filter(id=self.poll.id).update(**generate_poll_phase_kwargs('prediction_vote'))
        response = generate_request(api=PollProposalKPIVoteAPI,
                                    user=self.group_user_two.user,
                                    url_params=dict(proposal_id=self.proposal_one.id),
                                    data=dict(kpi_id=self.group_kpi_one.id,
                                              vote=22))

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(PollProposalKPIVote.objects.filter(created_by=self.group_user_two, vote=22).exists())

    def test_kpi_bet_list(self):
        [PollProposalKPIBetFactory(kpi_value=GroupKPIValue.objects.get(kpi=self.group_kpi_one, value=i),
                                   proposal=self.proposal_one,
                                   created_by=self.group_user_one) for i in [12, 22, 29]]

        response = generate_request(api=PollProposalKPIBetListAPI,
                                    user=self.group_user_one.user,
                                    data=dict(kpi_ids=f'{self.group_kpi_one.id}'),
                                    url_params=dict(group_id=self.group.id))

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['count'], 3)

    def test_kpi_vote_list(self):
        [PollProposalKPIBetFactory(kpi_value=GroupKPIValue.objects.get(kpi=self.group_kpi_one, value=i),
                                   proposal=self.proposal_one,
                                   created_by=self.group_user_one) for i in [12, 22, 29]]

        Poll.objects.filter(id=self.poll.id).update(**generate_poll_phase_kwargs('prediction_vote'))

        PollProposalKPIVote.objects.create(created_by=self.group_user_two,
                                           proposal=self.proposal_one,
                                           kpi=self.group_kpi_one,
                                           vote=22)

        response = generate_request(api=PollProposalKPIVoteListAPI,
                                    user=self.group_user_two.user,
                                    url_params=dict(group_id=self.group.id))

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['count'], 1)
