from django.urls import path

from backend.settings import URL_SUBPATH
from .consumers import ChatConsumer
from .views import (ChannelListAPI, ChannelDetailAPI, DirectChannelAPI, GroupChatCreateAPI, ChannelInviteAPI,
                    ChannelInviteAcceptAPI, ChannelInviteDeclineAPI, ChannelLeaveAPI, ChannelUpdateAPI,
                    ChannelReadAPI, ChannelMemberListAPI, MessageListAPI, MessageChannelTopicListAPI,
                    MessageFileCollectionUploadAPI)

subpath = f'{URL_SUBPATH}/' if URL_SUBPATH else ''

chat_patterns = [
    path('channel/list', ChannelListAPI.as_view(), name='channel_list'),
    path('channel/direct', DirectChannelAPI.as_view(), name='channel_direct'),
    path('channel/create', GroupChatCreateAPI.as_view(), name='channel_create'),
    path('channel/<int:channel_id>', ChannelDetailAPI.as_view(), name='channel_detail'),
    path('channel/<int:channel_id>/invite', ChannelInviteAPI.as_view(), name='channel_invite'),
    path('channel/<int:channel_id>/accept', ChannelInviteAcceptAPI.as_view(), name='channel_accept'),
    path('channel/<int:channel_id>/decline', ChannelInviteDeclineAPI.as_view(), name='channel_decline'),
    path('channel/<int:channel_id>/leave', ChannelLeaveAPI.as_view(), name='channel_leave'),
    path('channel/<int:channel_id>/update', ChannelUpdateAPI.as_view(), name='channel_update'),
    path('channel/<int:channel_id>/read', ChannelReadAPI.as_view(), name='channel_read'),
    path('channel/<int:channel_id>/member/list', ChannelMemberListAPI.as_view(), name='channel_member_list'),
    path('channel/<int:channel_id>/message/list', MessageListAPI.as_view(), name='message_list'),
    path('channel/<int:channel_id>/topic/list', MessageChannelTopicListAPI.as_view(),
         name='message_channel_topic_list'),
    path('channel/<int:channel_id>/file/upload', MessageFileCollectionUploadAPI.as_view(),
         name='message_channel_file_upload'),
]

chat_ws_patterns = [
    path(subpath + 'chat/ws', ChatConsumer.as_asgi(), name='ws_chat'),
]
