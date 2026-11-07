from django.apps import AppConfig


class PaymentAggregatorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.payment_aggregator"
    label = "payment_aggregator"
    verbose_name = "Payment Aggregator"
