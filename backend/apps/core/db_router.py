from typing import Any

OWNER_DB = "owner"


class MigrationsAsOwnerRouter:
    """Schema changes only ever run through the `owner` connection.

    The app connection (`default`, role billing_app) owns nothing and can
    alter nothing; `manage.py migrate --database=owner` is the one way to
    apply migrations. Queries always use `default`, so RLS applies.
    """

    def db_for_read(self, model: type[Any], **hints: Any) -> str:
        return "default"

    def db_for_write(self, model: type[Any], **hints: Any) -> str:
        return "default"

    def allow_migrate(self, db: str, app_label: str, **hints: Any) -> bool:
        return db == OWNER_DB
