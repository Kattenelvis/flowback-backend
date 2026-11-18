from django.contrib.auth import logout
from django.core.exceptions import ValidationError
from drf_spectacular.utils import extend_schema
from phonenumber_field.serializerfields import PhoneNumberField
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from knox.views import LoginView as KnoxLoginView
from knox.models import AuthToken

from backend.settings import DEBUG_REGISTER_BYPASS_EMAIL_VERIFICATION
from flowback.common.pagination import LimitOffsetPagination, get_paginated_response
from rest_framework.response import Response
from rest_framework.views import APIView

from flowback.notification.views import NotificationSubscribeTemplateAPI
from flowback.user.models import User
from flowback.user.selectors import get_user, user_list
from flowback.user.services import (user_create,
                                    user_create_verify,
                                    user_forgot_password,
                                    user_forgot_password_verify,
                                    user_update,
                                    user_delete,
                                    user_notification_subscribe,
                                    user_bookmark_create,
                                    user_bookmark_delete)


class UserLoginAPI(KnoxLoginView):
    permission_classes = (AllowAny, )

    class InputSerializer(serializers.Serializer):
        email = serializers.EmailField()
        password = serializers.CharField()

        def validate(self, attrs):
            email = attrs.get('email')
            password = attrs.get('password')

            # Same error for unknown user and wrong password to prevent user enumeration
            user = User.objects.filter(email__iexact=email).first()
            if user is None:
                # Run the password hasher anyway so response time doesn't reveal whether the user exists
                User().set_password(password)
                raise ValidationError('Wrong email or password')

            if not user.check_password(password):
                raise ValidationError('Wrong email or password')

            attrs['user'] = user
            return attrs

    def post(self, request, format=None):
        serializer = self.InputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = AuthToken.objects.create(user=serializer.validated_data['user'])[1]
        return Response(data=token, status=status.HTTP_200_OK)


class UserCreateApi(APIView):
    permission_classes = [AllowAny]

    class InputSerializer(serializers.Serializer):
        email = serializers.EmailField()

    def post(self, request):
        serializer = self.InputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        onboard_user = user_create(**serializer.validated_data)

        data = None
        if DEBUG_REGISTER_BYPASS_EMAIL_VERIFICATION:
            data = onboard_user.verification_code

        return Response(status=status.HTTP_200_OK, data=data)


class UserCreateVerifyApi(APIView):
    permission_classes = [AllowAny]

    class InputSerializer(serializers.Serializer):
        username = serializers.CharField()
        verification_code = serializers.UUIDField()
        password = serializers.CharField()

    def post(self, request):
        serializer = self.InputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = user_create_verify(**serializer.validated_data)
        instance, token = AuthToken.objects.create(user=user)
        return Response(status=status.HTTP_201_CREATED, data=token)


class UserForgotPasswordApi(APIView):
    permission_classes = [AllowAny]

    class InputSerializer(serializers.Serializer):
        email = serializers.EmailField()

    def post(self, request):
        serializer = self.InputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        password_reset = user_forgot_password(**serializer.validated_data)

        data = None
        if DEBUG_REGISTER_BYPASS_EMAIL_VERIFICATION:
            data = password_reset.verification_code

        return Response(status=status.HTTP_200_OK, data=data)


class UserForgotPasswordVerifyApi(APIView):
    permission_classes = [AllowAny]

    class InputSerializer(serializers.Serializer):
        verification_code = serializers.UUIDField()
        password = serializers.CharField()

    def post(self, request):
        serializers = self.InputSerializer(data=request.data)
        serializers.is_valid(raise_exception=True)

        user = user_forgot_password_verify(**serializers.validated_data)
        token, created = AuthToken.objects.create(user=user)[1]

        return Response(status=status.HTTP_200_OK, data=token)


class UserListApi(APIView):

    class Pagination(LimitOffsetPagination):
        default_limit = 1
        max_limit = 1000

    class FilterSerializer(serializers.Serializer):
        id = serializers.IntegerField(required=False)
        username = serializers.CharField(required=False)
        username__icontains = serializers.CharField(required=False)

    class OutputSerializer(serializers.ModelSerializer):

        class Meta:
            model = User
            fields = ('id', 'username', 'profile_image', 'is_active', 'banner_image', 'public_status', 'chat_status')

    def get(self, request):
        filter_serializer = self.FilterSerializer(data=request.query_params)
        filter_serializer.is_valid(raise_exception=True)

        users = user_list(fetched_by=request.user, filters=filter_serializer.validated_data)

        return get_paginated_response(pagination_class=self.Pagination,
                                      serializer_class=self.OutputSerializer,
                                      queryset=users,
                                      request=self.request,
                                      view=self)


class UserGetApi(APIView):

    class FilterSerializer(serializers.Serializer):
        user_id = serializers.IntegerField(required=False)

    class OutputSerializer(serializers.Serializer):
        id = serializers.IntegerField()
        username = serializers.CharField()
        profile_image = serializers.ImageField()
        banner_image = serializers.ImageField()

        bio = serializers.CharField(required=False)
        website = serializers.CharField(required=False)
        contact_email = serializers.CharField(required=False)
        contact_phone = PhoneNumberField(required=False)
        public_status = serializers.BooleanField(required=False)
        chat_status = serializers.BooleanField(required=False)

        email = serializers.CharField(required=False)
        dark_theme = serializers.BooleanField(required=False)
        user_config = serializers.CharField(required=False)

    def get(self, request):
        serializer = self.FilterSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        user = get_user(fetched_by=request.user, **serializer.validated_data)

        serializer = self.OutputSerializer(user)
        return Response(serializer.data)


class UserUpdateApi(APIView):

    class InputSerializer(serializers.Serializer):
        username = serializers.CharField(required=False)
        profile_image = serializers.ImageField(required=False, allow_null=True)
        banner_image = serializers.ImageField(required=False, allow_null=True)
        bio = serializers.CharField(required=False, allow_null=True)
        website = serializers.CharField(required=False, allow_null=True)
        dark_theme = serializers.BooleanField(required=False)
        contact_email = serializers.CharField(required=False, allow_null=True)
        contact_phone = PhoneNumberField(required=False, allow_null=True)
        public_status = serializers.ChoiceField(required=False, choices=User.PublicStatus.choices)
        chat_status = serializers.ChoiceField(required=False, choices=User.PublicStatus.choices)
        email = serializers.CharField(required=False)
        user_config = serializers.CharField(required=False, allow_null=True)

    def post(self, request):
        serializer = self.InputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_update(user=request.user, data=serializer.validated_data)
        return Response(status=status.HTTP_200_OK)


class UserDeleteAPI(APIView):

    def post(self, request):
        user_delete(user_id=request.user.id)

        return Response(status=status.HTTP_200_OK)


@extend_schema(description=User.notification_docs())
class UserNotificationSubscribeAPI(NotificationSubscribeTemplateAPI):
    lazy_action = user_notification_subscribe


class UserLogoutAPI(APIView):

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_200_OK)


class UserBookmarkCreateAPI(APIView):

    class InputSerializer(serializers.Serializer):
        object_id = serializers.IntegerField()
        content_type = serializers.CharField()

    def post(self, request):
        serializer = self.InputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_bookmark_create(user_id=request.user.id, **serializer.validated_data)

        return Response(status=status.HTTP_201_CREATED)


class UserBookmarkDeleteAPI(APIView):

    class InputSerializer(serializers.Serializer):
        object_id = serializers.IntegerField()
        content_type = serializers.CharField()

    def post(self, request):
        serializer = self.InputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_bookmark_delete(user_id=request.user.id, **serializer.validated_data)

        return Response(status=status.HTTP_200_OK)
