from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import serializers, status

from flowback.common.fields import CharacterSeparatedField
from flowback.group.selectors.kpi import group_kpi_list
from flowback.group.services.kpi import group_kpi_create, group_kpi_update


class GroupKPIListAPI(APIView):
    class FilterSerializer(serializers.Serializer):
        id = serializers.IntegerField(required=False)
        name = serializers.CharField(required=False)
        name__icontains = serializers.CharField(required=False)
        description = serializers.CharField(required=False)
        description__icontains = serializers.CharField(required=False)
        active = serializers.BooleanField(allow_null=True, required=False, default=None)

    class OutputSerializer(serializers.Serializer):
        name = serializers.CharField()
        description = serializers.CharField(allow_null=True)
        active = serializers.BooleanField()
        values = serializers.ListField(child=serializers.IntegerField())

    def get(self, request, group_id: int):
        serializer = self.FilterSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        data = group_kpi_list(fetched_by=request.user, group_id=group_id, filters=serializer.validated_data)

        return Response(data=self.OutputSerializer(data, many=True).data)


class GroupKPICreateAPI(APIView):
    class InputSerializer(serializers.Serializer):
        name = serializers.CharField()
        description = serializers.CharField(required=False)
        values = CharacterSeparatedField(child=serializers.IntegerField())

    def post(self, request, group_id: int):
        serializer = self.InputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        kpi = group_kpi_create(user_id=request.user.id, group_id=group_id, **serializer.validated_data)

        return Response(status=status.HTTP_201_CREATED, data=kpi.id)


class GroupKPIUpdateAPI(APIView):
    class InputSerializer(serializers.Serializer):
        active = serializers.BooleanField()

    def post(self, request, kpi_id: int):
        serializer = self.InputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        group_kpi_update(user_id=request.user.id, kpi_id=kpi_id, **serializer.validated_data)
        return Response(status=status.HTTP_200_OK)