# payment-aggregator

Provider-neutral payment aggregator for Indonesian payment gateways: pay-in
billings (virtual account, credit card, e-commerce), payouts (disbursements),
transaction / withdrawal fee calculation and signed callbacks.

Plain Python (3.9+). No web framework, no database, no global state.
Dependencies: `requests`, `cryptography`.

Providers included: **DANA** (Gapura Custom Checkout, cancel, refund,
Disbursement to Bank) and **DOKU** (Checkout, Kirim DOKU).

## Install

From this repository (path or git URL):

```bash
pip install -e ./libs/payment_aggregator
pip install "payment-aggregator @ git+https://github.com/<org>/<repo>.git#subdirectory=libs/payment_aggregator"
```

## Usage

```python
from decimal import Decimal

from payment_aggregator import PaymentAggregator
from payment_aggregator.base import BillingRequest, RefundRequest, TransferRequest
from payment_aggregator.providers.dana import DanaConfig, DanaProvider

provider = DanaProvider(
    DanaConfig.from_env(),
    # Your contract rates. Flat channels take IDR, percent channels take a
    # percentage. Channels you leave out are not offered.
    channel_fees={
        "VIRTUAL_ACCOUNT_BCA": Decimal("2775"),
        "NETWORK_PAY_PG_CARD": Decimal("3.219"),
    },
    disbursement_fee=Decimal("2500"),
)
aggregator = PaymentAggregator(provider)

aggregator.get_channels(Decimal("150000"))          # fee + total per usable channel
aggregator.create_billing(BillingRequest(...))      # -> BillingResult
aggregator.get_billing_status(provider_trx_id)      # -> BillingResult
aggregator.parse_billing_callback(raw_body, headers, request_path)
if aggregator.can_cancel_billing():
    aggregator.cancel_billing(reference_no)         # -> CancelResult
if aggregator.can_refund():
    aggregator.refund_billing(RefundRequest(...))   # -> RefundResult
aggregator.calculate_withdrawal(Decimal("100000"))  # -> WithdrawalBreakdown
aggregator.transfer_balance(TransferRequest(...))   # -> TransferResult
aggregator.get_transfer_status(provider_transfer_id)
```

Keep one aggregator per merchant account wherever suits your app (a module
global, a Django app, a dependency-injection container...).

## Configuration

Each provider reads its credentials with `<Provider>Config.from_env()`; the
variables are listed at the top of `providers/dana/config.py` and
`providers/doku/config.py`. You can also build the config dataclass directly.
PEM values may contain real newlines or literal `
`.

Channel codes: `providers/<name>/constants.py` (`CHANNELS`). Payout bank
codes (shared by every provider): `payment_aggregator.banks.BANKS`.

## Errors

Every error subclasses `payment_aggregator.exceptions.PaymentAggregatorError`
and carries a stable `code` (e.g. `PROVIDER_UNAVAILABLE`, `CHANNEL_NOT_AVAILABLE`).
`ProviderUnavailable` means the outcome is unknown: never assume the request failed.

## Testing your app

`payment_aggregator.testing` has `FakeSession`, `FakeResponse`, `key_pair()` and
`make_dana_provider()` / `make_doku_provider()` to run a real provider against
canned HTTP responses.

## Adding a provider

Subclass `payment_aggregator.base.BaseProvider`, return the neutral dataclasses
from `payment_aggregator.base`, and raise the errors from
`payment_aggregator.exceptions`. Business code does not change.

## Running the library tests

```bash
pip install -e ./libs/payment_aggregator
python -m unittest discover -s libs/payment_aggregator/tests -t libs/payment_aggregator
```
