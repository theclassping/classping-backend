from decimal import Decimal

from django.db import migrations, models


def backfill_balance_after(apps, schema_editor):
    """Running branch total (available + pending) in entry order."""
    LedgerEntry = apps.get_model("wallets", "LedgerEntry")
    totals = {}
    for entry in LedgerEntry.objects.order_by("branch_id", "pk").only("pk", "branch_id", "amount").iterator():
        totals[entry.branch_id] = totals.get(entry.branch_id, Decimal("0")) + entry.amount
        LedgerEntry.objects.filter(pk=entry.pk).update(balance_after=totals[entry.branch_id])


class Migration(migrations.Migration):

    dependencies = [
        ("wallets", "0002_withdrawals"),
    ]

    operations = [
        migrations.AddField(
            model_name="ledgerentry",
            name="balance_after",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_balance_after, migrations.RunPython.noop),
    ]
