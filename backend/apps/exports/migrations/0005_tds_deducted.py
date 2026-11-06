"""Exports: the register of TDS we deducted on vendor bills (payables, Part B)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("exports", "0004_tally"),
        ("payables", "0001_initial"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="export",
            name="exports_kind_check",
        ),
        migrations.AlterField(
            model_name="export",
            name="kind",
            field=models.TextField(
                choices=[('DOCUMENTS', 'Documents'), ('PAYMENTS', 'Payments'), ('EXPENSES', 'Expenses'), ('RECEIVABLES', 'Receivables'), ('GSTR1', 'Gstr1'), ('BOQ', 'Boq'), ('PROJECTS', 'Projects'), ('STATEMENT', 'Statement'), ('TALLY', 'Tally'), ('TDS_DEDUCTED', 'Tds Deducted')]
            ),
        ),
        migrations.AddConstraint(
            model_name="export",
            constraint=models.CheckConstraint(
                condition=models.Q(("kind__in", ['DOCUMENTS', 'PAYMENTS', 'EXPENSES', 'RECEIVABLES', 'GSTR1', 'BOQ', 'PROJECTS', 'STATEMENT', 'TALLY', 'TDS_DEDUCTED'])),
                name="exports_kind_check",
            ),
        ),
    ]
