import base64
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
        "JWT_SIGNING_KEY": "j" * 64,
        "MFA_ENCRYPTION_KEY": base64.b64encode(b"k" * 32).decode(),
        "CLAMD_HOST": "clamav.internal",
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


def test_prod_refuses_dev_jwt_and_mfa_keys() -> None:
    for name, value in [
        ("JWT_SIGNING_KEY", "local-dev-jwt-signing-key-not-a-secret-0123456789"),
        ("MFA_ENCRYPTION_KEY", base64.b64encode(b"local-dev-mfa-key-32-bytes-long!").decode()),
    ]:
        result = _import_prod_settings(**{name: value})
        assert result.returncode != 0
        assert name in result.stderr


def test_prod_refuses_to_run_without_a_virus_scanner() -> None:
    result = _import_prod_settings(CLAMD_HOST="")
    assert result.returncode != 0
    assert "CLAMD_HOST" in result.stderr


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


def test_openapi_schema_generates_without_warnings(tmp_path: Path) -> None:
    """The schema is the contract for web and mobile: every endpoint documented."""
    result = subprocess.run(
        [
            sys.executable,
            "manage.py",
            "spectacular",
            "--fail-on-warn",
            "--format",
            "openapi-json",
            "--file",
            str(tmp_path / "schema.json"),
        ],
        cwd=BACKEND_DIR,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.test"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    # The web app generates its API types from the committed copy. JSON, not YAML:
    # YAML readers disagree on values like 08 (a string here, a number in YAML 1.2).
    committed = BACKEND_DIR / "openapi.json"
    assert committed.read_text(encoding="utf-8") == (tmp_path / "schema.json").read_text(
        encoding="utf-8"
    ), (
        "backend/openapi.json is out of date. Regenerate it with\n"
        "  DJANGO_SETTINGS_MODULE=config.settings.test uv run python manage.py"
        " spectacular --format openapi-json --file openapi.json\n"
        "then run `npm run gen:api` in web/."
    )


def test_openapi_has_no_bare_array_responses() -> None:
    """Every list answer is an object ({results, next_cursor} or {results, totals}); a
    documented bare array means a view's extend_schema disagrees with its Response."""
    import json

    schema = json.loads((BACKEND_DIR / "openapi.json").read_text(encoding="utf-8"))
    bare = [
        f"{method.upper()} {path} {status}"
        for path, ops in schema["paths"].items()
        for method, op in ops.items()
        for status, response in op.get("responses", {}).items()
        if response.get("content", {}).get("application/json", {}).get("schema", {}).get("type")
        == "array"
    ]
    assert bare == []
