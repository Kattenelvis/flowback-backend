from rest_framework import serializers

from flowback.files.serializers import FileSerializer


class ChatUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    profile_image = serializers.ImageField(allow_null=True)


class MessageSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    channel_id = serializers.IntegerField()
    user = ChatUserSerializer()
    message = serializers.CharField()
    type = serializers.CharField()
    event = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    parent_id = serializers.IntegerField(allow_null=True)
    topic_id = serializers.IntegerField(allow_null=True)
    attachments = FileSerializer(many=True, source='attachments.file_collection.filesegment_set', allow_null=True)


class ChannelMemberSerializer(serializers.Serializer):
    user = ChatUserSerializer()
    status = serializers.CharField()


class ChannelSerializer(serializers.Serializer):
    """A chat as one user sees it. Built by selectors.channel_summaries."""
    id = serializers.IntegerField()
    kind = serializers.CharField()
    title = serializers.CharField(allow_null=True, help_text="For direct messages, the other person's username")
    status = serializers.CharField(help_text="The user's membership: 'active' or 'invited'")
    member_count = serializers.IntegerField(help_text="Number of active members")
    other_user = ChatUserSerializer(allow_null=True, help_text="The other person in a direct message")
    invited_by = ChatUserSerializer(allow_null=True)
    last_message = MessageSerializer(allow_null=True, help_text="The last message someone wrote, ignoring info messages")
    last_activity = serializers.DateTimeField(help_text="When anything was last posted, or when the user was added")
    last_read_at = serializers.DateTimeField(allow_null=True)
    unread_count = serializers.IntegerField()
    can_leave = serializers.BooleanField()
    can_rename = serializers.BooleanField()
    can_invite = serializers.BooleanField()
