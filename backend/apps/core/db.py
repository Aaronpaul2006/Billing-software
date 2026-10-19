"""Field types, lookups and helpers for mirroring db/schema.sql in Django models.

The models must produce *exactly* the schema in db/schema.sql (the sync test
in tests/db/test_schema_sync.py compares the two catalogs), so this module
provides the few SQL shapes Django lacks: citext, char(n), char_length,
octet_length, `<>`, `NOT IN`, raw SQL defaults, and foreign keys whose
constraints are created by RunSQL (composite, tenant-scoped) instead of Django.
"""

import uuid
from typing import Any

from django.contrib.postgres.functions import RandomUUID
from django.db import models
from django.db.models import Func, Transform
from django.db.models.lookups import In, Lookup, Regex


class CITextField(models.TextField):  # type: ignore[type-arg]
    """PostgreSQL citext (case-insensitive text), e.g. email addresses."""

    def db_type(self, connection: Any) -> str:
        return "citext"


class FixedCharField(models.CharField):  # type: ignore[type-arg]
    """char(n) instead of Django's varchar(n), for codes of fixed length."""

    def db_type(self, connection: Any) -> str:
        return f"char({self.max_length})"


@FixedCharField.register_lookup
class FixedCharRegex(Regex):
    """`col ~ 'pattern'` with no ::text cast. PostgreSQL has a regex operator
    for char(n) itself, which is what db/schema.sql uses."""

    def process_lhs(self, compiler: Any, connection: Any, lhs: Any = None) -> Any:
        return Lookup.process_lhs(self, compiler, connection, lhs)


class SQLDefault(Func):
    """A column default written as raw SQL, e.g. now() (not Django's
    STATEMENT_TIMESTAMP()) or now() + interval '24 hours'."""

    def __init__(self, sql: str, output_field: models.Field[Any, Any]) -> None:
        super().__init__(template=sql, output_field=output_field)
        self.sql = sql

    def deconstruct(self) -> tuple[str, tuple[Any, ...], dict[str, Any]]:
        return "apps.core.db.SQLDefault", (self.sql, self.output_field), {}


class NumNonNulls(Func):
    function = "num_nonnulls"
    output_field = models.IntegerField()


@models.CharField.register_lookup
@models.TextField.register_lookup
class CharLength(Transform):
    lookup_name = "char_length"
    function = "char_length"
    output_field = models.IntegerField()


@models.BinaryField.register_lookup
class OctetLength(Transform):
    lookup_name = "octet_length"
    function = "octet_length"
    output_field = models.IntegerField()


@models.CharField.register_lookup
@models.TextField.register_lookup
class StatePrefix(Transform):
    """substr(gstin, 1, 2): the state code embedded in a GSTIN."""

    lookup_name = "state_prefix"
    template = "substr(%(expressions)s, 1, 2)"


@models.Field.register_lookup
class NotEqual(Lookup):  # type: ignore[type-arg]
    """`col <> value` (Django's ~Q(col=value) renders NOT (col = value))."""

    lookup_name = "ne"

    def as_sql(self, compiler: Any, connection: Any) -> tuple[str, list[Any]]:
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        return f"{lhs} <> {rhs}", [*lhs_params, *rhs_params]


@models.Field.register_lookup
class NotIn(In):  # type: ignore[type-arg]
    lookup_name = "not_in"

    def get_rhs_op(self, connection: Any, rhs: str) -> str:
        return f"NOT IN {rhs}"


def now_default() -> SQLDefault:
    return SQLDefault("now()", models.DateTimeField())


def uuid7_pk() -> models.UUIDField:  # type: ignore[type-arg]
    """App-generated UUIDv7 (time ordered); gen_random_uuid() for raw SQL inserts."""
    return models.UUIDField(
        primary_key=True, default=uuid.uuid7, db_default=RandomUUID(), editable=False
    )


def created_at() -> models.DateTimeField:  # type: ignore[type-arg]
    return models.DateTimeField(auto_now_add=True, db_default=now_default())


def updated_at() -> models.DateTimeField:  # type: ignore[type-arg]
    return models.DateTimeField(auto_now=True, db_default=now_default())


def ref(
    to: str,
    *,
    null: bool = False,
    db_column: str | None = None,
    related_name: str = "+",
    on_delete: Any = models.PROTECT,
) -> Any:
    """A ForeignKey for ORM joins only.

    The database constraint is created by RunSQL exactly as in db/schema.sql:
    composite (tenant_id, x_id) between tenant tables, because PostgreSQL
    skips RLS during FK checks. Django's own constraint (single column,
    DEFERRABLE) and its automatic index are therefore disabled; indexes are
    declared explicitly in Meta.indexes, mirroring the schema.
    """
    return models.ForeignKey(
        to,
        on_delete=on_delete,
        null=null,
        blank=null,
        db_column=db_column,
        db_constraint=False,
        db_index=False,
        related_name=related_name,
    )


def tenant_ref() -> Any:
    return ref("tenants.Tenant")


def tenant_id_key(table: str) -> models.UniqueConstraint:
    """UNIQUE (tenant_id, id): the target of every composite foreign key."""
    return models.UniqueConstraint(fields=["tenant", "id"], name=f"{table}_tenant_id_id_key")


def between(field: str, low: Any, high: Any, name: str) -> models.CheckConstraint:
    return models.CheckConstraint(condition=models.Q(**{f"{field}__range": (low, high)}), name=name)


def one_of(field: str, values: list[str], name: str) -> models.CheckConstraint:
    return models.CheckConstraint(condition=models.Q(**{f"{field}__in": values}), name=name)


def regex(field: str, pattern: str, name: str) -> models.CheckConstraint:
    return models.CheckConstraint(condition=models.Q(**{f"{field}__regex": pattern}), name=name)


def length_between(field: str, low: int, high: int, name: str) -> models.CheckConstraint:
    return between(f"{field}__char_length", low, high, name)


def non_negative(field: str, name: str) -> models.CheckConstraint:
    return models.CheckConstraint(condition=models.Q(**{f"{field}__gte": 0}), name=name)
