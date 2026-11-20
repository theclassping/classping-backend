"""Errors raised by the package. Each has a stable ``code`` for API responses."""


class SubscriptionError(Exception):
    code = "SUBSCRIPTION_ERROR"
    status = 400

    def __init__(self, message="", **extra):
        super().__init__(message or self.__doc__ or self.code)
        self.message = message or (self.__doc__ or self.code).strip()
        self.extra = extra


class SubscriptionNotFound(SubscriptionError):
    """This subscriber has no subscription."""

    code = "SUBSCRIPTION_NOT_FOUND"
    status = 404


class FeatureLocked(SubscriptionError):
    """The subscription has expired; this feature is read-only until it is renewed."""

    code = "FEATURE_LOCKED"
    status = 403

    def __init__(self, feature, state, message=""):
        super().__init__(message, feature=feature, state=state)
        self.feature = feature
        self.state = state


class LimitReached(SubscriptionError):
    """This would go over the plan's limit."""

    code = "LIMIT_REACHED"
    status = 403

    def __init__(self, feature, limit, used, adding, message=""):
        super().__init__(message, feature=feature, limit=limit, used=used, adding=adding)
        self.feature = feature
        self.limit = limit
        self.used = used
        self.adding = adding


class InvalidRequest(SubscriptionError):
    code = "INVALID_REQUEST"


class InvoiceNotPayable(SubscriptionError):
    """This invoice is not open."""

    code = "INVOICE_NOT_PAYABLE"


class AddonNotAllowed(SubscriptionError):
    """Add-ons can only be bought on a trialing or active subscription."""

    code = "ADDON_REQUIRES_ACTIVE_SUBSCRIPTION"


class AddonQuantityExceeded(SubscriptionError):
    """This would go over the add-on's maximum quantity."""

    code = "ADDON_QUANTITY_EXCEEDED"


class PlanChangeNotAllowed(SubscriptionError):
    code = "PLAN_CHANGE_NOT_ALLOWED"


class BillingNotSupported(SubscriptionError):
    """Online payment is not available; pay by bank transfer and ask an admin to mark it paid."""

    code = "BILLING_NOT_SUPPORTED"
