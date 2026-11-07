"""
Provider-neutral errors raised by PaymentAggregator.

Each error carries a stable ``code`` that API layers can map to the error
codes in the proposal (e.g. PROVIDER_UNAVAILABLE, CHANNEL_NOT_AVAILABLE).
"""


class PaymentAggregatorError(Exception):
    code = "PAYMENT_AGGREGATOR_ERROR"

    def __init__(self, message="", *, provider_message="", raw=None):
        super().__init__(message or self.code)
        self.message = message or self.code
        self.provider_message = provider_message
        self.raw = raw


class ProviderNotConfigured(PaymentAggregatorError):
    code = "PROVIDER_NOT_CONFIGURED"


class ProviderUnavailable(PaymentAggregatorError):
    """Network error, timeout, 5xx, or an unparseable response.

    The outcome of the request is UNKNOWN: callers must not assume it failed
    (e.g. never reverse a withdrawal on this error).
    """

    code = "PROVIDER_UNAVAILABLE"


class ProviderAccessDenied(PaymentAggregatorError):
    """HTTP 403: IP not whitelisted or our request signature was rejected."""

    code = "PROVIDER_ACCESS_DENIED"


class ProviderRejected(PaymentAggregatorError):
    """The provider processed the request and returned a business error."""

    code = "PROVIDER_REJECTED"


class BillingNotFound(ProviderRejected):
    code = "BILLING_NOT_FOUND"


class TransferNotFound(ProviderRejected):
    code = "TRANSFER_NOT_FOUND"


class DuplicateBilling(ProviderRejected):
    """The billing reference was already used; ``provider_trx_id`` is the existing one."""

    code = "DUPLICATE_BILLING"

    def __init__(self, message="", *, provider_trx_id="", **kwargs):
        super().__init__(message, **kwargs)
        self.provider_trx_id = provider_trx_id


class DuplicateTransfer(ProviderRejected):
    code = "DUPLICATE_TRANSFER"


class InsufficientProviderBalance(ProviderRejected):
    code = "PROVIDER_BALANCE_INSUFFICIENT"


class InvalidDestinationAccount(ProviderRejected):
    code = "PAYOUT_ACCOUNT_INVALID"


class TransferAmountOutOfRange(ProviderRejected):
    code = "TRANSFER_AMOUNT_OUT_OF_RANGE"


class InvalidCallback(PaymentAggregatorError):
    """Callback signature / token / body could not be verified."""

    code = "INVALID_CALLBACK"


# --- Fee / limit validation (raised by fees.py) ---------------------------


class ChannelNotAvailable(PaymentAggregatorError):
    code = "CHANNEL_NOT_AVAILABLE"


class InvalidAmount(PaymentAggregatorError):
    code = "INVALID_AMOUNT"


class AmountBelowMinimum(PaymentAggregatorError):
    code = "AMOUNT_BELOW_MINIMUM"


class AmountAboveMaximum(PaymentAggregatorError):
    code = "AMOUNT_ABOVE_MAXIMUM"
