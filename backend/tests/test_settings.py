import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings
from django.template.loader import get_template
from django.test import Client

from config.settings import base

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEV_PLACEHOLDER = "local-dev-insecure-secret-key-do-not-use"


def test_production_hashes_passwords_with_argon2() -> None:
    assert base.PASSWORD_HASHERS[0] == "django.contrib.auth.hashers.Argon2PasswordHasher"


def test_every_request_is_a_transaction() -> None:
    assert settings.DATABASES["default"]["ATOMIC_REQUESTS"] is True


def test_money_is_serialised_as_string() -> None:
    assert settings.REST_FRAMEWORK["COERCE_DECIMAL_TO_STRING"] is True


def _import_prod_settings(**overrides: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.prod",
        "DJANGO_ALLOWED_HOSTS": "api.example.com",
        "DJANGO_SECRET_KEY": "x" * 64,
        **overrides,
    }
    return subprocess.run(
        [sys.executable, "-c", "import django; django.setup()"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_prod_settings_load_with_proper_configuration() -> None:
    result = _import_prod_settings()
    assert result.returncode == 0, result.stderr


def test_prod_refuses_weak_secret_key() -> None:
    result = _import_prod_settings(DJANGO_SECRET_KEY=DEV_PLACEHOLDER)
    assert result.returncode != 0
    assert "DJANGO_SECRET_KEY" in result.stderr


def test_prod_refuses_missing_allowed_hosts() -> None:
    result = _import_prod_settings(DJANGO_ALLOWED_HOSTS="")
    assert result.returncode != 0
    assert "DJANGO_ALLOWED_HOSTS" in result.stderr


def test_api_docs_template_is_available() -> None:
    # /api/v1/docs/ (dev only) renders this template; without TEMPLATES it 500s.
    get_template("drf_spectacular/swagger_ui.html")


@pytest.mark.django_db
def test_openapi_schema_is_3_1(client: Client) -> None:
    response = client.get("/api/v1/schema/", headers={"Accept": "application/json"})
    assert response.status_code == 200
    assert response.json()["openapi"].startswith("3.1")
