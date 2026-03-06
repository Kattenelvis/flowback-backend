from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from backend.settings import TESTING

from flowback.chat.models import MessageChannelParticipant, Message


def send_join_leave_message(instance):
    channel_layer = get_channel_layer()

    async_to_sync(channel_layer.group_send)(
        f"{instance.channel.id}",
        dict(type="info",
             channel_id=instance.channel.id,
             method="message_notify",
             message=f"User {instance.user.username} {'joined' if instance.active else 'left'} the channel")
    )

    Message.objects.create(user=instance.user,
                           channel=instance.channel,
                           message=f"User {instance.user.username} {'joined' if instance.active else 'left'}"
                                   f" the channel",
                           type="info")


@receiver(post_save, sender=MessageChannelParticipant)
def message_channel_participant_post_save(sender, instance, created, update_fields, **kwargs):
    update_fields = update_fields or []

    if update_fields:
        if not all(isinstance(field, str) for field in update_fields):
            update_fields = [field.name for field in update_fields]

    if (created and instance.active) or (not created and "active" in update_fields):
        if not TESTING:
            send_join_leave_message(instance)


@receiver(post_delete, sender=MessageChannelParticipant)
def message_channel_participant_post_delete(sender, instance, **kwargs):
    if instance.active and not TESTING:  # Send message to group
            send_join_leave_message(instance)
