"""
Classping's PaymentAggregator: the ``payment_aggregator`` library configured
with Classping's providers, rates and credentials.

    from apps.payment_aggregator import PaymentAggregator

    PaymentAggregator.get_channels(invoice_total)
    PaymentAggregator.calculate_transaction_fee("VABCA", invoice_total)
    PaymentAggregator.create_billing(BillingRequest(...))
    PaymentAggregator.calculate_withdrawal(amount)
    PaymentAggregator.transfer_balance(TransferRequest(...))

``PaymentAggregator`` is the ACTIVE provider, chosen with env
PAYMENT_PROVIDER (settings.PAYMENT_PROVIDER, default "rintisan"). Every new
checkout and withdrawal goes to it and stores its name in ``provider``.

A record that already exists must keep talking to the provider that created
it, even after PAYMENT_PROVIDER is switched (status sync, expiry, settlement,
callbacks, resend):

    PaymentAggregator.using(gateway_payment.provider).get_billing_status(...)

Providers are the modules in apps/payment_aggregator/providers/ (see its
__init__ for how to add one). They are built on first use (credentials are
read from the environment then), once per process.
"""

import threading

from django.conf import settings
from payment_aggregator import PaymentAggregator as _PaymentAggregator
from payment_aggregator.exceptions import InvalidCallback, ProviderNotConfigured

from apps.payment_aggregator import providers

_lock = threading.Lock()
_aggregators = {}  # provider name -> library PaymentAggregator
_active_override = None  # set by set_provider() (tests)


def provider_names():
    return providers.names()


def active_provider_name():
    if _active_override is not None:
        return _active_override
    return settings.PAYMENT_PROVIDER


def get_aggregator(name=None):
    """The library aggregator for provider ``name`` (default: the active one).

    Raises ProviderNotConfigured for a name with no builder (e.g. a typo in
    PAYMENT_PROVIDER, or a record from a provider that was removed).
    """
    name = name or active_provider_name()
    aggregator = _aggregators.get(name)
    if aggregator is not None:
        return aggregator
    with _lock:
        if name not in _aggregators:
            _aggregators[name] = _PaymentAggregator(build_provider(name))
        return _aggregators[name]


def parse_callback(method, raw_body, headers, provider=None, request_path=""):
    """Verify and parse a provider callback; returns (provider_name, result).

    ``method`` is "parse_billing_callback" or "parse_transfer_callback".
    With ``provider`` (provider-specific URL) only that provider is tried.
    Without it (generic URL /api/webhooks/<event>/) the active provider is
    tried first, then every other one: the provider whose signature/token
    verifies the body is the sender. Providers without credentials are
    skipped. Raises InvalidCallback when no provider accepts the body.
    """
    if provider:
        names = [provider]
    else:
        active = active_provider_name()
        names = [active] + [name for name in _known_names() if name != active]
    last_error = None
    for name in names:
        try:
            # Through the proxy, so mock.patch on PaymentAggregator applies.
            return name, getattr(PaymentAggregator.using(name), method)(
                raw_body, headers, request_path=request_path
            )
        except (InvalidCallback, ProviderNotConfigured) as error:
            last_error = error
    raise last_error or InvalidCallback("No payment provider accepted the callback")


def callback_reply(provider, event, default):
    """The reply to a provider notification: the provider's required
    acknowledgement (DANA: responseCode + X-TIMESTAMP) or ``default``."""
    from apps.core.webhooks import WebhookReply

    try:
        reply = PaymentAggregator.using(provider).callback_reply(event)
    except ProviderNotConfigured:
        reply = None
    if reply is None:
        return default
    body, headers = reply
    return WebhookReply(body, headers)


def _known_names():
    # Builders plus providers installed directly (tests).
    return list(dict.fromkeys(list(providers.names()) + list(_aggregators)))


def build_provider(name=None):
    """A new provider instance for ``name`` (default: the active one)."""
    name = name or active_provider_name()
    module = providers.get(name)
    if module is None:
        raise ProviderNotConfigured(
            "Unknown payment provider {!r} (known: {})".format(name, ", ".join(providers.names()))
        )
    return module.build()


def get_provider(name=None):
    return get_aggregator(name).provider


def set_provider(provider):
    """Make ``provider`` the active one, dropping every other (tests).
    Pass None to reset to PAYMENT_PROVIDER."""
    global _active_override
    with _lock:
        _aggregators.clear()
        if provider is None:
            _active_override = None
        else:
            _aggregators[provider.name] = _PaymentAggregator(provider)
            _active_override = provider.name


def add_provider(provider):
    """Install another provider next to the active one (tests)."""
    with _lock:
        _aggregators[provider.name] = _PaymentAggregator(provider)


class _ClasspingAggregator:
    """Forwards every call to a process-wide aggregator, so callers (and
    mock.patch targets such as "...PaymentAggregator.create_billing") work
    without holding an instance.

    The module-level ``PaymentAggregator`` follows the active provider;
    ``using(name)`` gives one bound to a stored record's provider."""

    def __init__(self, name=None):
        self._name = name

    def using(self, name):
        """Aggregator for the provider that created a record. Returns the
        active one itself when ``name`` is active (or empty, for records
        older than the ``provider`` field)."""
        if not name or name == active_provider_name():
            return PaymentAggregator
        return _ClasspingAggregator(name)

    def __getattr__(self, name):
        return getattr(get_aggregator(self._name), name)


PaymentAggregator = _ClasspingAggregator()
