import inspect
from typing import Type

from faker import Faker
from django.test.client import MULTIPART_CONTENT, encode_multipart, BOUNDARY
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from flowback.user.models import User

fake = Faker()


def generate_request(api: Type[APIView],
                     data: dict | bytes = None,
                     url_params: dict = None,
                     user: User = None,
                     multipart: bool = False):

    if url_params is None:
        url_params = dict()

    factory = APIRequestFactory()
    method = [i[0] for i in inspect.getmembers(api, predicate=inspect.isfunction)]
    view = api.as_view()

    if all(['get' in method, 'post' in method]):
        raise NotImplementedError('generate_request is unable to handle requests with both get/post methods.')

    extra_kwargs = dict(format='json')
    if multipart:
        if isinstance(data, dict):
            data = encode_multipart(data=data, boundary=BOUNDARY)

        extra_kwargs = dict(content_type=MULTIPART_CONTENT)


    if 'get' in method:
        request = factory.get('', data=data, **extra_kwargs)

    elif 'post' in method:
        request = factory.post('', data=data, **extra_kwargs)

    else:
        raise NotImplementedError('Missing handling for APIView method besides get/post.')

    if user:
        force_authenticate(request, user=user)

    return view(request, **url_params)
