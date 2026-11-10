from celery import shared_task

from . import services


@shared_task
def poll_processing_withdrawals_task():
    """Every 5 minutes: backup to the disbursement callback."""
    return services.poll_processing_withdrawals()


@shared_task
def check_branch_balances_task():
    """23:00: wallets of branches with ledger changes today vs their ledger."""
    return len(services.check_branch_balances())
