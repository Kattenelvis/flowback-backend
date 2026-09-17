from drf_spectacular.utils import extend_schema

from rest_framework import serializers, status
from rest_framework.views import APIView, Response

from flowback.common.pagination import LimitOffsetPagination, get_paginated_response
from flowback.common.services import get_object

from flowback.poll.models import Poll
from flowback.poll.selectors.vote import poll_vote_list, delegate_poll_vote_list
from flowback.poll.serializers import PollSerializer
from flowback.poll.services.vote import poll_proposal_vote_update, poll_proposal_delegate_vote_update

from flowback.group.serializers import GroupUserSerializer


@extend_schema(tags=['poll/vote'])
class PollProposalVoteListAPI(APIView):
    class Pagination(LimitOffsetPagination):
        default_limit = 10

    class FilterSerializer(serializers.Serializer):
        created_by_user_id = serializers.IntegerField(required=False)
        proposal_id = serializers.IntegerField(required=False)
        delegates = serializers.BooleanField(required=False, default=False)
        delegate_pool_id = serializers.IntegerField(required=False)
        delegate_user_id = serializers.IntegerField(required=False)

    def get(self, request, poll: int):
        poll = get_object(Poll, id=poll)
        filter_serializer = self.FilterSerializer(data=request.query_params)
        filter_serializer.is_valid(raise_exception=True)
        delegates = filter_serializer.validated_data.pop('delegates')

        votes = poll_vote_list(fetched_by=request.user, poll_id=poll.id,
                               delegates=delegates,
                               filters=filter_serializer.validated_data)

        return get_paginated_response(
            pagination_class=self.Pagination,
            serializer_class=poll.poll_type_new.vote_output_serializer_class(),
            queryset=votes,
            request=request,
            view=self
        )


# TODO need fixes
class DelegatePollVoteListAPI(APIView):
    class Pagination(LimitOffsetPagination):
        max_limit = 100
        default_limit = 25

    class InputSerializer(serializers.Serializer):
        group_id = serializers.IntegerField()
        delegate_pool_id = serializers.IntegerField(required=False)
        poll_id = serializers.IntegerField(required=False)

    class OutputSerializer(serializers.Serializer):
        poll = PollSerializer()
        vote = serializers.SerializerMethodField()

        class VoteCardinalOutputSerializer(serializers.Serializer):
            proposal_id = serializers.IntegerField()
            proposal_title = serializers.CharField(source='proposal.title')
            proposal_description = serializers.CharField(source='proposal.description')
            proposal_created_by = GroupUserSerializer(source='proposal.created_by', hide_relevant_users=True)
            score = serializers.IntegerField(allow_null=True)
            raw_score = serializers.IntegerField()

            class Meta:
                ordering = ['priority']

        def get_vote(self, obj):
            serializer = self.VoteCardinalOutputSerializer(obj.pollvotingtypecardinal_set,
                                                            many=True,
                                                            allow_null=True,
                                                            required=False)

            return serializer.data

    def get(self, request):
        serializer = self.InputSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        votes = delegate_poll_vote_list(fetched_by=request.user,
                                        **serializer.validated_data)

        return get_paginated_response(
            pagination_class=self.Pagination,
            serializer_class=self.OutputSerializer,
            queryset=votes,
            request=request,
            view=self
        )


@extend_schema(tags=['poll/vote'])
class PollProposalVoteUpdateAPI(APIView):
    def post(self, request, poll: int):
        poll = get_object(Poll, id=poll)
        serializer = poll.poll_type_new.vote_input_serializer_class()(data=request.data)
        serializer.is_valid(raise_exception=True)
        poll_proposal_vote_update(user_id=request.user.id, poll_id=poll.id, data=serializer.validated_data)
        return Response(status=status.HTTP_200_OK)


@extend_schema(tags=['poll/vote'])
class PollProposalDelegateVoteUpdateAPI(APIView):
    def post(self, request, poll: int):
        poll = get_object(Poll, id=poll)
        serializer = poll.poll_type_new.delegate_vote_input_serializer_class()(data=request.data)
        serializer.is_valid(raise_exception=True)
        poll_proposal_delegate_vote_update(user_id=request.user.id, poll_id=poll.id, data=serializer.validated_data)
        return Response(status=status.HTTP_200_OK)
