from django.apps import AppConfig


class PaymentGatewayConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.payment_gateway"
    label = "payment_gateway"
    verbose_name = "Payment Gateway"
