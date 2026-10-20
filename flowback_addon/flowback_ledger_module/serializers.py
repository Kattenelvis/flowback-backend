from rest_framework import serializers
from flowback.user.serializers import BasicUserSerializer


class AccountSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    account_number = serializers.CharField()
    account_name = serializers.CharField()

    created_by = BasicUserSerializer(source='user')
