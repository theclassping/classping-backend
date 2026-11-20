from celery import shared_task


@shared_task
def advance_statuses_task():
    """Hourly: write past_due / expired, roll paid periods, close stale checkouts."""
    from plan_subscriptions import services

    from . import payments

    return {"statuses": services.advance_statuses(), "payments_closed": payments.expire_overdue()}


@shared_task
def issue_due_invoices_task():
    from plan_subscriptions import services

    return services.issue_due_invoices()


@shared_task
def send_reminders_task():
    from plan_subscriptions import services

    return services.send_reminders()
