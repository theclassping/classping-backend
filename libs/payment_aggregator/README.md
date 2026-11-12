# payment-aggregator

Provider-neutral payment aggregator for Indonesian payment gateways: pay-in
billings (virtual account, credit card, e-commerce), payouts (disbursements),
transaction / withdrawal fee calculation and signed callbacks.

Plain Python (3.9+). No web framework, no database, no global state.
Dependencies: `requests`, `cryptography`.

Providers included: **Rintisan**.

## Install

From this repository (path or git URL):

```bash
pip install ./libs/payment_aggregator
pip install "payment-aggregator @ git+https://github.com/<org>/<repo>.git#subdirectory=libs/payment_aggregator"
```

## Usage

```python
from decimal import Decimal

from payment_aggregator import PaymentAggregator
from payment_aggregator.base import BillingRequest
from payment_aggregator.providers.rintisan import RintisanConfig, RintisanProvider

provider = RintisanProvider(
    RintisanConfig.from_env(),
    # Your contract rates. Flat channels take IDR, percent channels take a
    # percentage. Channels you leave out are not offered.
    channel_fees={
        "VABCA": Decimal("5000"),
        "VABNI": Decimal("5000"),
        "CC": Decimal("2"),
    },
    disbursement_fee=Decimal("2500"),
)
aggregator = PaymentAggregator(provider)

aggregator.get_channels(Decimal("150000"))          # fee + total per usable channel
aggregator.create_billing(BillingRequest(...))      # -> BillingResult
aggregator.parse_billing_callback(raw_body, headers)
aggregator.calculate_withdrawal(Decimal("100000"))  # -> WithdrawalBreakdown
aggregator.transfer_balance(TransferRequest(...))   # -> TransferResult
```

Keep one aggregator per merchant account wherever suits your app (a module
global, a Django app, a dependency-injection container...).

## Rintisan configuration

`RintisanConfig.from_env()` reads:

| Variable | Meaning |
| --- | --- |
| `RINTISAN_ENV` | `sandbox` (default) or `production` |
| `RINTISAN_BASE_URL` | optional base URL override |
| `RINTISAN_CLIENT_ID` | `x-client-id` |
| `RINTISAN_API_KEY` | `x-api-key` |
| `RINTISAN_PRIVATE_KEY` | your RSA private key (PEM), signs requests |
| `RINTISAN_PUBLIC_KEY` | Rintisan RSA public key (PEM), verifies callbacks |
| `RINTISAN_CALLBACK_TOKEN` | expected `x-callback-token` on callbacks |
| `RINTISAN_PAYER_EMAIL` | `to_email` sent on every billing (empty: the request's payer email) |
| `RINTISAN_REQUIRE_TRANSFER_CALLBACK_SIGNATURE` | `true` (default) / `false` |

PEM values may contain real newlines or literal `\n`. The private key
variable name can be changed: `RintisanConfig.from_env(private_key_env="MY_APP_PRIVATE_KEY")`.
You can also build `RintisanConfig(...)` directly instead of reading the environment.

Available channel codes and bank codes: `payment_aggregator.providers.rintisan.constants`
(`CHANNELS`, `BANK_CODES`).

## Errors

Every error subclasses `payment_aggregator.exceptions.PaymentAggregatorError`
and carries a stable `code` (e.g. `PROVIDER_UNAVAILABLE`, `CHANNEL_NOT_AVAILABLE`).
`ProviderUnavailable` means the outcome is unknown: never assume the request failed.

## Testing your app

`payment_aggregator.testing` has `FakeSession`, `FakeResponse`, `key_pair()` and
`make_provider()` (Rintisan) to run a real provider against canned HTTP responses.

## Adding a provider

Subclass `payment_aggregator.base.BaseProvider`, return the neutral dataclasses
from `payment_aggregator.base`, and raise the errors from
`payment_aggregator.exceptions`. Business code does not change.

## Running the library tests

```bash
pip install ./libs/payment_aggregator
python -m unittest discover -s libs/payment_aggregator/tests -t libs/payment_aggregator
```
