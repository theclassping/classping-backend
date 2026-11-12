"""
Classping's payment providers: one module per provider.

Add a provider:
  1. Implement it in the library (libs/payment_aggregator/.../providers/<name>/).
  2. Copy rintisan.py to <name>.py here and fill in NAME, CHANNEL_FEES,
     DISBURSEMENT_FEE and build().
  3. Add its dotted path to PROVIDER_MODULES below.
  4. Add its env vars to .env / .env.production.example.
It is then selectable with PAYMENT_PROVIDER=<name> and gets its webhook URLs.

Every provider module exposes:
  NAME              value of PAYMENT_PROVIDER and of ``provider`` on records
  CHANNEL_FEES      {channel code: fee}; flat rupiah or percent per the
                    library's channel table; a channel left out is not offered
  DISBURSEMENT_FEE  fee per withdrawal, or None when withdrawals are not set up
  build()           returns a configured library provider; raises
                    ProviderNotConfigured when it cannot be used yet
"""

from importlib import import_module

PROVIDER_MODULES = (
    "apps.payment_aggregator.providers.rintisan",
    "apps.payment_aggregator.providers.dana",
)

_registry = None


def registry():
    """{provider name: provider module}, in PROVIDER_MODULES order."""
    global _registry
    if _registry is None:
        modules = [import_module(path) for path in PROVIDER_MODULES]
        _registry = {module.NAME: module for module in modules}
    return _registry


def get(name):
    """The provider module for ``name``, or None."""
    return registry().get(name)


def names():
    return tuple(registry())
