"""Test-only endpoints exercising the shared API building blocks."""

from typing import Any

from django.urls import include, path
from rest_framework import serializers
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import CatalogItem
from apps.core.errors import Invalid
from apps.core.fields import MoneyField
from apps.core.idempotency import idempotent


class _ItemSerializer(serializers.ModelSerializer[CatalogItem]):
    default_rate = MoneyField(required=False, allow_null=True)

    class Meta:
        model = CatalogItem
        fields = ("id", "name", "default_rate")


class CreateItemView(APIView):
    @idempotent
    def post(self, request: Request) -> Response:
        data = _ItemSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        if data.validated_data["name"] == "fail after writing":
            CatalogItem.objects.create(name="half-done")
            raise Invalid("name", "Failing on purpose.")
        item = data.save()
        return Response(_ItemSerializer(item).data, status=201)


class ListItemsView(ListAPIView[CatalogItem]):
    serializer_class = _ItemSerializer
    ordering_fields = ("name",)

    def get_queryset(self) -> Any:
        return CatalogItem.objects.all()


urlpatterns = [
    path("api/v1/test/items", CreateItemView.as_view()),
    path("api/v1/test/items/list", ListItemsView.as_view()),
    path("", include("config.urls")),
]
