"""Let the app role read (only read) Django's migration history.

`manage.py runserver` and other management commands check for unapplied
migrations through the default connection, i.e. as billing_app. Read access
reveals nothing but migration names; applying migrations still needs the
owner (manage.py migrate --database=owner).
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("core", "0003_database_security")]

    operations = [
        migrations.RunSQL(
            "GRANT SELECT ON django_migrations TO billing_app;",
            "REVOKE SELECT ON django_migrations FROM billing_app;",
        )
    ]
