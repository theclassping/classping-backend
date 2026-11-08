from celery import shared_task

from . import services


@shared_task
def poll_processing_withdrawals_task():
    """Every 5 minutes: backup to the disbursement callback."""
    return services.poll_processing_withdrawals()
