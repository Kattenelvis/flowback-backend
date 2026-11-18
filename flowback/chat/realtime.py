"""Pushes chat events to connected websockets.

Each websocket joins one channel-layer group per chat it is an active member of, plus a
personal group for its user. Events about a chat go to that chat's group. Events about one
user's membership go to their personal group, which also tells their open websockets to start
or stop listening to the chat, so membership changes take effect without reconnecting.

Everything is sent after the current database transaction commits, so clients never hear about
changes that were rolled back.
"""
import json
import logging
from typing import Callable

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction

logger = logging.getLogger(__name__)

Payload = dict | Callable[[], dict]


def user_group_name(user_id: int) -> str:
    return f"chat_user_{user_id}"


def channel_group_name(channel_id: int) -> str:
    return f"chat_channel_{channel_id}"


def _send(group: str, message: dict) -> None:
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    try:
        async_to_sync(channel_layer.group_send)(group, message)
    except Exception:
        logger.exception("Failed to send chat event to %s", group)


def _send_event(group: str, event: Payload, handler: str = "chat.event", **extra) -> None:
    if callable(event):
        event = event()
        if event is None:  # Nothing left to tell, e.g. the chat was deleted
            return

    # Channel layers can only carry plain JSON types, not datetimes or serializer dicts
    event = json.loads(json.dumps(event, cls=DjangoJSONEncoder))
    _send(group, {"type": handler, "event": event, **extra})


def publish_to_channel(channel_id: int, event: Payload) -> None:
    """Sends an event to every active member of a chat.

    A callable event is built when it is sent, and may return None to send nothing.
    """
    transaction.on_commit(lambda: _send_event(channel_group_name(channel_id), event,
                                              handler="chat.channel_event", channel_id=channel_id), robust=True)


def publish_to_user(user_id: int, event: Payload) -> None:
    """Sends an event to every open websocket of one user. A callable event is built when it is sent."""
    transaction.on_commit(lambda: _send_event(user_group_name(user_id), event), robust=True)


def subscribe(user_id: int, channel_id: int) -> None:
    """Makes the user's open websockets start receiving a chat's events."""
    transaction.on_commit(lambda: _send(user_group_name(user_id),
                                        {"type": "chat.subscribe", "channel_id": channel_id}), robust=True)


def unsubscribe(user_id: int, channel_id: int) -> None:
    """Makes the user's open websockets stop receiving a chat's events."""
    transaction.on_commit(lambda: _send(user_group_name(user_id),
                                        {"type": "chat.unsubscribe", "channel_id": channel_id}), robust=True)
