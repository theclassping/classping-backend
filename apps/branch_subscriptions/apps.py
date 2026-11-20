from django.apps import AppConfig


class BranchSubscriptionsConfig(AppConfig):
    """Classping wiring for plan_subscriptions: the branch is the subscriber."""

    name = "apps.branch_subscriptions"
    label = "branch_subscriptions"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import signals  # noqa: F401
