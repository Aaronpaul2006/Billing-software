from collections.abc import Iterator
from typing import Any

import pytest
from django.db import connections
from django.test.utils import setup_databases, teardown_databases


@pytest.fixture(scope="session")
def django_db_setup(
    request: pytest.FixtureRequest,
    django_test_environment: None,
    django_db_blocker: Any,
    django_db_keepdb: bool,
) -> Iterator[None]:
    """Always create the test database through the `owner` alias.

    `default` (the app role) mirrors `owner`, so the owner creates and
    migrates test_<name> and tests then query it as billing_app, under RLS.
    pytest-django would only set up the aliases tests ask for (`default`),
    which leaves the mirror pointing at the real database; never allow that.
    """
    verbosity = request.config.option.verbose
    with django_db_blocker.unblock():
        config = setup_databases(
            verbosity=verbosity,
            interactive=False,
            keepdb=django_db_keepdb,
            aliases={"default", "owner"},  # type: ignore[arg-type]  # stubs say Mapping
        )
        for alias in ("default", "owner"):
            name = connections[alias].settings_dict["NAME"]
            assert name.startswith("test_"), f"{alias} points at non-test database {name}"
    yield
    with django_db_blocker.unblock():
        connections.close_all()  # the app connection would block DROP DATABASE
        teardown_databases(config, verbosity=verbosity, keepdb=django_db_keepdb)


@pytest.fixture
def committed_db(django_db_setup: None, django_db_blocker: Any) -> Iterator[None]:
    """Database access with real COMMITs (no per-test wrapping transaction).

    Needed to test transaction boundaries and concurrency. pytest-django's
    transaction=True would TRUNCATE all tables afterwards, which the app role
    may not do (and audit_log forbids); instead each test creates its own
    tenants with fresh ids, and the whole test database is dropped at the end
    of the session.
    """
    with django_db_blocker.unblock():
        yield
        connections["default"].close()
