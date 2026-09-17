from django.contrib.auth.models import AnonymousUser
from knox.auth import TokenAuthentication
from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from rest_framework.exceptions import AuthenticationFailed


@database_sync_to_async
def get_user(token):
    try:
        user, token = TokenAuthentication().authenticate_credentials(token=bytes(token, 'utf-8'))
        return user
    except AuthenticationFailed:
        return AnonymousUser()


class TokenAuthMiddleware(BaseMiddleware):
    def __init__(self, inner):
        super().__init__(inner)

    async def __call__(self, scope, receive, send):
        try:
            token_key = (dict((x.split('=') for x in scope['query_string'].decode().split("&")))).get('token', None)
        except ValueError:
            token_key = None
        scope['user'] = AnonymousUser() if token_key is None else await get_user(token_key)
        return await super().__call__(scope, receive, send)