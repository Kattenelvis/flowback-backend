import django_filters
from django.db.models import Q, OuterRef, Subquery, Count, Exists, IntegerField, QuerySet
from django.db.models.functions import Coalesce
from rest_framework.exceptions import ValidationError

from .models import MessageChannel, Message, MessageChannelParticipant, MessageChannelTopic
from flowback.user.models import User
from ..common.filters import NumberInFilter, ExistsFilter

Status = MessageChannelParticipant.Status


def get_membership(*, user_id: int, channel_id: int, statuses=(Status.ACTIVE,)) -> MessageChannelParticipant:
    """Returns the user's membership of a chat, or raises if it isn't in one of the given statuses."""
    participant = (MessageChannelParticipant.objects
                   .select_related('channel')
                   .filter(user_id=user_id, channel_id=channel_id, status__in=statuses)
                   .first())

    if participant is None:
        raise ValidationError("You are not a member of this chat")

    return participant


class ChannelFilter(django_filters.FilterSet):
    kind = django_filters.CharFilter(field_name='channel__kind')
    status = django_filters.ChoiceFilter(choices=[(Status.ACTIVE, 'Active'), (Status.INVITED, 'Invited')])
    search = django_filters.CharFilter(method='filter_search')

    def filter_search(self, queryset, name, value):
        # Direct messages have no title, so they're found by the other person's username
        other_member_matches = MessageChannelParticipant.objects.filter(
            channel_id=OuterRef('channel_id'),
            user__username__icontains=value
        ).exclude(user_id=OuterRef('user_id'))

        return queryset.filter(Q(channel__title__icontains=value)
                               | Q(channel__kind=MessageChannel.Kind.USER) & Exists(other_member_matches))

    class Meta:
        model = MessageChannelParticipant
        fields = dict(channel_id=['exact'])


def channel_list(*, user: User, filters=None) -> QuerySet[MessageChannelParticipant]:
    """The user's chats and chat invites, most recently active first."""
    filters = filters or {}

    channel_messages = Message.objects.filter(channel_id=OuterRef('channel_id'), active=True)
    latest = channel_messages.order_by('-id')
    # Shown as the chat's preview, so info messages like "User X joined" don't hide what was last said
    last_message = latest.filter(type=Message.Type.MESSAGE)

    unread_messages = (channel_messages
                       .filter(type=Message.Type.MESSAGE,
                               created_at__gt=Coalesce(OuterRef('last_read_at'), OuterRef('created_at')))
                       .exclude(user_id=user.id)
                       .order_by()
                       .values('channel_id')
                       .annotate(count=Count('id'))
                       .values('count'))

    active_members = (MessageChannelParticipant.objects
                      .filter(channel_id=OuterRef('channel_id'), status=Status.ACTIVE)
                      .order_by()
                      .values('channel_id')
                      .annotate(count=Count('id'))
                      .values('count'))

    qs = (MessageChannelParticipant.objects
          .filter(user=user, status__in=[Status.ACTIVE, Status.INVITED])
          .select_related('channel', 'invited_by')
          .annotate(last_message_id=Subquery(last_message.values('id')[:1]),
                    last_activity=Coalesce(Subquery(latest.values('created_at')[:1]), 'created_at'),
                    unread_count=Coalesce(Subquery(unread_messages, output_field=IntegerField()), 0),
                    member_count=Coalesce(Subquery(active_members, output_field=IntegerField()), 0))
          .order_by('-last_activity', '-id'))

    return ChannelFilter(filters, qs).qs


def channel_get(*, user: User, channel_id: int) -> MessageChannelParticipant:
    participant = channel_list(user=user).filter(channel_id=channel_id).first()

    if participant is None:
        raise ValidationError("You are not a member of this chat")

    return participant


def channel_summaries(*, user: User, participants: list[MessageChannelParticipant]) -> list[dict]:
    """Turns rows from channel_list into what ChannelSerializer outputs, with a fixed number of queries."""
    messages = (Message.objects
                .filter(id__in=[p.last_message_id for p in participants if p.last_message_id])
                .select_related('user', 'attachments__file_collection')
                .prefetch_related('attachments__file_collection__filesegment_set')
                .in_bulk())

    dm_channel_ids = [p.channel_id for p in participants if p.channel.kind == MessageChannel.Kind.USER]
    other_users = {member.channel_id: member.user
                   for member in (MessageChannelParticipant.objects
                                  .filter(channel_id__in=dm_channel_ids)
                                  .exclude(user=user)
                                  .select_related('user'))}

    summaries = []
    for participant in participants:
        channel = participant.channel
        policy = channel.policy
        other_user = other_users.get(channel.id)
        is_active = participant.is_active

        summaries.append(dict(
            id=channel.id,
            kind=channel.kind,
            title=other_user.username if other_user else channel.title,
            status=participant.status,
            member_count=participant.member_count,
            other_user=other_user,
            invited_by=participant.invited_by,
            last_message=messages.get(participant.last_message_id) if is_active else None,
            last_activity=participant.last_activity,
            last_read_at=participant.last_read_at,
            unread_count=participant.unread_count if is_active else 0,
            can_leave=is_active and policy.can_leave,
            can_rename=is_active and policy.can_rename,
            can_invite=is_active and policy.can_invite,
        ))

    return summaries


def channel_summary(*, user: User, channel_id: int) -> dict:
    return channel_summaries(user=user, participants=[channel_get(user=user, channel_id=channel_id)])[0]


def channel_member_list(*, user: User, channel_id: int) -> QuerySet[MessageChannelParticipant]:
    get_membership(user_id=user.id, channel_id=channel_id)

    return (MessageChannelParticipant.objects
            .filter(channel_id=channel_id, status__in=[Status.ACTIVE, Status.INVITED])
            .select_related('user')
            .order_by('status', 'user__username'))


class MessageFilter(django_filters.FilterSet):
    before_id = django_filters.NumberFilter(field_name='id', lookup_expr='lt')
    topic_name = django_filters.CharFilter(lookup_expr='exact', field_name='topic__name')
    user_ids = NumberInFilter(field_name='user_id')
    has_attachments = ExistsFilter(field_name='attachments')

    class Meta:
        model = Message
        fields = dict(id=['exact'],
                      message=['icontains'],
                      topic_id=['exact'],
                      parent_id=['exact'],
                      created_at=['gte', 'lte'])


def message_list(*, user: User, channel_id: int, filters=None) -> QuerySet[Message]:
    """Messages in a chat, newest first. Page backwards with before_id."""
    filters = filters or {}
    get_membership(user_id=user.id, channel_id=channel_id)

    qs = (Message.objects
          .filter(channel_id=channel_id, active=True)
          .select_related('user', 'attachments__file_collection')
          .prefetch_related('attachments__file_collection__filesegment_set')
          .order_by('-id'))

    return MessageFilter(filters, qs).qs


class TopicFilter(django_filters.FilterSet):
    class Meta:
        model = MessageChannelTopic
        fields = dict(id=['exact'],
                      name=['exact', 'icontains'])


def message_channel_topic_list(*, user: User, channel_id: int, filters=None):
    filters = filters or {}
    get_membership(user_id=user.id, channel_id=channel_id)

    qs = MessageChannelTopic.objects.filter(channel_id=channel_id).all()
    return TopicFilter(filters, qs).qs
