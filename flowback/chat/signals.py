from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from backend.settings import TESTING

from flowback.chat.models import MessageChannelParticipant
from flowback.chat.services import send_channel_info_message


# TODO: Fix this
# Uncomment below only when testing chat ws in django tests
# TESTING = False


@receiver(post_save, sender=MessageChannelParticipant)
def message_channel_participant_post_save(sender, instance, created, update_fields, **kwargs):
    update_fields = update_fields or []

    if update_fields:
        if not all(isinstance(field, str) for field in update_fields):
            update_fields = [field.name for field in update_fields]

    if (created and instance.active) or (not created and "active" in update_fields):
        if not TESTING:
            send_channel_info_message(instance,
                                      f"User {instance.user.username} {'joined' if instance.active else 'left'}"
                                      f" the channel")


@receiver(post_delete, sender=MessageChannelParticipant)
def message_channel_participant_post_delete(sender, instance, **kwargs):
    if instance.active and not TESTING:  # Send message to group
        send_channel_info_message(instance, f"User {instance.user.username} left"
                                            f" the channel")
