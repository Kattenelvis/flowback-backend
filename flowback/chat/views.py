from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from flowback.common.pagination import get_paginated_response, LimitOffsetPagination
from .selectors import (channel_list, channel_summaries, channel_summary, channel_member_list, message_list,
                        message_channel_topic_list)
from .serializers import ChannelSerializer, ChannelMemberSerializer, MessageSerializer
from .services import (direct_channel_get_or_create, group_chat_create, channel_invite, channel_invite_accept,
                       channel_invite_decline, channel_leave, channel_rename, channel_mark_read, message_files_upload)


def channel_response(request, channel_id: int, status_code=status.HTTP_200_OK) -> Response:
    return Response(status=status_code,
                    data=ChannelSerializer(channel_summary(user=request.user, channel_id=channel_id)).data)


@extend_schema(responses=ChannelSerializer(many=True))
class ChannelListAPI(APIView):
    """The user's chats and chat invites, most recently active first."""
    class Pagination(LimitOffsetPagination):
        default_limit = 30
        max_limit = 100

    class FilterSerializer(serializers.Serializer):
        kind = serializers.ChoiceField(required=False, choices=['user', 'user_group', 'group', 'workgroup'])
        status = serializers.ChoiceField(required=False, choices=['active', 'invited'])
        search = serializers.CharField(required=False, help_text="Matches titles, and usernames in direct messages")
        channel_id = serializers.IntegerField(required=False)

    def get(self, request):
        serializer = self.FilterSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        qs = channel_list(user=request.user, filters=serializer.validated_data)
        paginator = self.Pagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        summaries = channel_summaries(user=request.user, participants=page)

        return paginator.get_paginated_response(ChannelSerializer(summaries, many=True).data)


@extend_schema(responses=ChannelSerializer)
class ChannelDetailAPI(APIView):
    def get(self, request, channel_id: int):
        return channel_response(request, channel_id)


@extend_schema(responses=ChannelSerializer)
class DirectChannelAPI(APIView):
    """Opens the direct message with a user, creating it if needed. Opening it accepts any invite to it."""
    class InputSerializer(serializers.Serializer):
        user_id = serializers.IntegerField()

    def post(self, request):
        serializer = self.InputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        channel = direct_channel_get_or_create(user=request.user, target_user_id=serializer.validated_data['user_id'])
        return channel_response(request, channel.id)


@extend_schema(responses=ChannelSerializer)
class GroupChatCreateAPI(APIView):
    """Creates a group chat and invites the given users to it."""
    class InputSerializer(serializers.Serializer):
        title = serializers.CharField(required=False, allow_blank=True, max_length=255)
        user_ids = serializers.ListField(child=serializers.IntegerField())

    def post(self, request):
        serializer = self.InputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        channel = group_chat_create(user=request.user, **serializer.validated_data)
        return channel_response(request, channel.id, status.HTTP_201_CREATED)


class ChannelInviteAPI(APIView):
    class InputSerializer(serializers.Serializer):
        user_ids = serializers.ListField(child=serializers.IntegerField())

    def post(self, request, channel_id: int):
        serializer = self.InputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        channel_invite(user=request.user, channel_id=channel_id, **serializer.validated_data)
        return Response(status=status.HTTP_200_OK)


@extend_schema(request=None, responses=ChannelSerializer)
class ChannelInviteAcceptAPI(APIView):
    def post(self, request, channel_id: int):
        channel_invite_accept(user=request.user, channel_id=channel_id)
        return channel_response(request, channel_id)


@extend_schema(request=None)
class ChannelInviteDeclineAPI(APIView):
    def post(self, request, channel_id: int):
        channel_invite_decline(user=request.user, channel_id=channel_id)
        return Response(status=status.HTTP_200_OK)


@extend_schema(request=None)
class ChannelLeaveAPI(APIView):
    def post(self, request, channel_id: int):
        channel_leave(user=request.user, channel_id=channel_id)
        return Response(status=status.HTTP_200_OK)


@extend_schema(responses=ChannelSerializer)
class ChannelUpdateAPI(APIView):
    class InputSerializer(serializers.Serializer):
        title = serializers.CharField(max_length=255)

    def post(self, request, channel_id: int):
        serializer = self.InputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        channel_rename(user=request.user, channel_id=channel_id, **serializer.validated_data)
        return channel_response(request, channel_id)


@extend_schema(request=None)
class ChannelReadAPI(APIView):
    """Marks every message in the chat as read."""
    def post(self, request, channel_id: int):
        channel_mark_read(user=request.user, channel_id=channel_id)
        return Response(status=status.HTTP_200_OK)


class ChannelMemberListAPI(APIView):
    class Pagination(LimitOffsetPagination):
        default_limit = 100
        max_limit = 1000

    OutputSerializer = ChannelMemberSerializer

    def get(self, request, channel_id: int):
        members = channel_member_list(user=request.user, channel_id=channel_id)

        return get_paginated_response(pagination_class=self.Pagination,
                                      queryset=members,
                                      request=request,
                                      view=self)


class MessageListAPI(APIView):
    """Messages in a chat, newest first. Load older messages with before_id."""
    class Pagination(LimitOffsetPagination):
        default_limit = 50
        max_limit = 100

    class FilterSerializer(serializers.Serializer):
        before_id = serializers.IntegerField(required=False)
        id = serializers.IntegerField(required=False)
        user_ids = serializers.CharField(required=False)
        message__icontains = serializers.CharField(required=False)
        parent_id = serializers.IntegerField(required=False)
        topic_id = serializers.IntegerField(required=False)
        topic_name = serializers.CharField(required=False)
        has_attachments = serializers.BooleanField(required=False, allow_null=True, default=None)
        created_at__gte = serializers.DateTimeField(required=False)
        created_at__lte = serializers.DateTimeField(required=False)

    OutputSerializer = MessageSerializer

    def get(self, request, channel_id: int):
        serializer = self.FilterSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        messages = message_list(user=request.user, channel_id=channel_id, filters=serializer.validated_data)

        return get_paginated_response(pagination_class=self.Pagination,
                                      queryset=messages,
                                      request=request,
                                      view=self)


class MessageChannelTopicListAPI(APIView):
    class Pagination(LimitOffsetPagination):
        default_limit = 50
        max_limit = 100

    class FilterSerializer(serializers.Serializer):
        id = serializers.IntegerField(required=False)
        name = serializers.CharField(required=False)
        name__icontains = serializers.CharField(required=False)

    class OutputSerializer(serializers.Serializer):
        id = serializers.IntegerField()
        name = serializers.CharField()

    def get(self, request, channel_id: int):
        serializer = self.FilterSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        topics = message_channel_topic_list(user=request.user, channel_id=channel_id, filters=serializer.validated_data)

        return get_paginated_response(pagination_class=self.Pagination,
                                      queryset=topics,
                                      request=request,
                                      view=self)


class MessageFileCollectionUploadAPI(APIView):
    class InputSerializer(serializers.Serializer):
        files = serializers.ListField(child=serializers.FileField())

    class OutputSerializer(serializers.Serializer):
        id = serializers.IntegerField()

    def post(self, request, channel_id: int):
        serializer = self.InputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        file_collection = message_files_upload(user_id=request.user.id, channel_id=channel_id,
                                               **serializer.validated_data)
        return Response(status=status.HTTP_201_CREATED, data=self.OutputSerializer(file_collection).data)
