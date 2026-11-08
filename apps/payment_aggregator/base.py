"""
Provider-neutral contract for payment aggregators.

Business code (payment_gateway, wallets) only sees the dataclasses and
statuses defined here, never provider-specific codes or payloads.
"""

import abc
import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Mapping, Optional, Sequence


class PaymentMethod:
    VIRTUAL_ACCOUNT = "virtual_account"
    CREDIT_CARD = "credit_card"
    E_COMMERCE = "e_commerce"


class FeeType:
    FLAT = "flat"
    PERCENT = "percent"


class BillingStatus:
    # Provider view of a billing. Expiry is a Classping rule (the provider
    # keeps reporting an unpaid billing as PENDING), not a provider status.
    PENDING = "pending"
    PAID = "paid"


class SettlementStatus:
    NOT_SETTLED = "not_settled"
    SETTLED = "settled"


class TransferStatus:
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"


# --- Fee configuration ----------------------------------------------------


@dataclass(frozen=True)
class Channel:
    code: str
    name: str
    method: str
    fee_type: str
    fee: Optional[Decimal]  # None = rate not agreed yet -> channel disabled
    min_amount: Optional[Decimal] = None
    max_amount: Optional[Decimal] = None
    is_active: bool = True


@dataclass(frozen=True)
class WithdrawalRules:
    fee: Decimal
    min_amount: Decimal
    max_amount: Decimal


# --- Calculation results --------------------------------------------------


@dataclass(frozen=True)
class FeeBreakdown:
    channel_code: str
    channel_name: str
    payment_method: str
    invoice_total: Decimal
    transaction_fee: Decimal
    amount: Decimal  # what the payer pays = invoice_total + transaction_fee


@dataclass(frozen=True)
class WithdrawalBreakdown:
    amount: Decimal  # debited from the branch balance
    fee: Decimal
    transfer_amount: Decimal  # sent to the bank account = amount - fee


# --- Provider requests / results ------------------------------------------


@dataclass(frozen=True)
class BillingRequest:
    reference_no: str
    channel_code: str
    amount: Decimal
    invoice_date: datetime.date
    # Classping payment window end (aware datetime); the provider decides how
    # to express it (Rintisan: deadline_date + expiry time).
    expires_at: datetime.datetime
    payer_name: str
    payer_phone: str
    # Providers may ignore this (Rintisan always sends its own PAYER_EMAIL).
    payer_email: str = ""
    identifier: str = ""
    payer_address: str = ""
    note: str = ""


@dataclass(frozen=True)
class BillingResult:
    reference_no: str
    provider_trx_id: str
    status: str = BillingStatus.PENDING
    settlement_status: str = SettlementStatus.NOT_SETTLED
    channel_code: str = ""
    amount: Optional[Decimal] = None
    payment_code: str = ""
    payment_link: str = ""
    billing_url: str = ""
    paid_at: Optional[datetime.datetime] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TransferRequest:
    reference_no: str
    amount: Decimal
    bank_code: str
    account_number: str
    account_name: str
    email: str = ""
    phone: str = ""


@dataclass(frozen=True)
class TransferResult:
    reference_no: str
    provider_transfer_id: str
    status: str
    provider_status_code: str = ""
    needs_review: bool = False
    amount_requested: Optional[Decimal] = None
    fee: Optional[Decimal] = None
    amount_received: Optional[Decimal] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderBalance:
    available: Decimal
    pending: Decimal
    raw: Dict[str, Any] = field(default_factory=dict)


# --- Provider interface ---------------------------------------------------


class BaseProvider(abc.ABC):
    """Every aggregator provider implements this interface."""

    name = ""

    # Fee configuration (numbers live in the provider's constants.py)
    @abc.abstractmethod
    def get_channels(self) -> Sequence[Channel]:
        ...

    @abc.abstractmethod
    def get_withdrawal_rules(self) -> WithdrawalRules:
        ...

    @abc.abstractmethod
    def get_banks(self) -> Mapping[str, str]:
        """Supported payout bank codes -> display names."""
        ...

    # Pay-in
    @abc.abstractmethod
    def create_billing(self, request: BillingRequest) -> BillingResult:
        ...

    @abc.abstractmethod
    def get_billing_status(self, provider_trx_id: str) -> BillingResult:
        ...

    @abc.abstractmethod
    def parse_billing_callback(self, raw_body: bytes, headers: Mapping[str, str]) -> BillingResult:
        ...

    # Payout
    @abc.abstractmethod
    def transfer_balance(self, request: TransferRequest) -> TransferResult:
        ...

    @abc.abstractmethod
    def get_transfer_status(self, provider_transfer_id: str) -> TransferResult:
        ...

    @abc.abstractmethod
    def parse_transfer_callback(self, raw_body: bytes, headers: Mapping[str, str]) -> TransferResult:
        ...

    @abc.abstractmethod
    def get_balance(self) -> ProviderBalance:
        ...
