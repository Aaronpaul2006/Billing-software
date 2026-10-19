import uuid
from typing import Any

import pytest
from django.db import transaction
from django.test import Client
from rest_framework import exceptions, serializers
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from apps.core.exceptions import flatten_validation_errors


class _Line(serializers.Serializer[Any]):
    rate = serializers.DecimalField(max_digits=14, decimal_places=2)


class _Doc(serializers.Serializer[Any]):
    party_id = serializers.UUIDField()
    lines = _Line(many=True)


class _ValidatingView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request: Request) -> Response:
        _Doc(data=request.data).is_valid(raise_exception=True)
        return Response(status=204)


class _ProtectedView(APIView):
    def get(self, request: Request) -> Response:
        return Response({"secret": True})


class _ThrottledView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request: Request) -> Response:
        raise exceptions.Throttled(wait=17)


def test_unknown_url_is_problem_json_with_request_id(client: Client) -> None:
    response = client.get("/no-such-page")
    assert response.status_code == 404
    assert response["Content-Type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "not_found"
    assert body["status"] == 404
    assert body["request_id"] == response["X-Request-ID"]


def test_request_id_is_server_generated_uuid7(client: Client) -> None:
    response = client.get("/healthz", headers={"X-Request-ID": "forged-by-client"})
    request_id = uuid.UUID(response["X-Request-ID"])
    assert request_id.version == 7


@pytest.mark.django_db  # ATOMIC_REQUESTS: every view runs in a transaction
def test_validation_error_is_422_with_field_paths() -> None:
    request = APIRequestFactory().post(
        "/x",
        {"party_id": "not-a-uuid", "lines": [{"rate": "1.00"}, {"rate": "1.005"}]},
        format="json",
    )
    request.request_id = "req-1"  # type: ignore[attr-defined]
    response = _ValidatingView.as_view()(request).render()  # headers are final once rendered

    assert response.status_code == 422
    assert response["Content-Type"] == "application/problem+json"
    body = response.data
    assert body["code"] == "validation_error"
    assert body["request_id"] == "req-1"
    fields = {e["field"]: e["code"] for e in body["errors"]}
    assert fields == {"party_id": "invalid", "lines[1].rate": "max_decimal_places"}
    assert body["detail"] == "2 fields are invalid."


@pytest.mark.django_db
def test_endpoints_require_authentication_by_default() -> None:
    response = _ProtectedView.as_view()(APIRequestFactory().get("/x"))
    assert response.status_code == 401
    assert response.data["code"] == "not_authenticated"
    assert response["WWW-Authenticate"] == 'Bearer realm="api"'
    assert "secret" not in response.data


def test_throttled_sets_retry_after() -> None:
    response = _ThrottledView.as_view()(APIRequestFactory().get("/x"))
    assert response.status_code == 429
    assert response["Retry-After"] == "17"
    assert response.data["code"] == "throttled"


def test_flatten_non_field_errors_use_parent_path() -> None:
    detail = {"lines": [{"non_field_errors": [exceptions.ErrorDetail("bad", code="invalid")]}]}
    assert flatten_validation_errors(detail) == [
        {"field": "lines[0]", "code": "invalid", "message": "bad"}
    ]


def test_flatten_handles_list_and_index_keyed_item_errors() -> None:
    err = [exceptions.ErrorDetail("too precise", code="max_decimal_places")]
    expected = [{"field": "lines[1].rate", "code": "max_decimal_places", "message": "too precise"}]
    assert flatten_validation_errors({"lines": [{}, {"rate": err}]}) == expected
    assert flatten_validation_errors({"lines": {1: {"rate": err}}}) == expected


@pytest.mark.django_db
def test_error_response_rolls_back_the_request_transaction() -> None:
    """A view that fails after writing must not commit (ATOMIC_REQUESTS)."""
    with transaction.atomic():  # stands in for the request transaction
        response = _ValidatingView.as_view()(APIRequestFactory().post("/x", {}, format="json"))
        assert response.status_code == 422
        assert transaction.get_rollback() is True
        transaction.set_rollback(False)  # let the test transaction continue
