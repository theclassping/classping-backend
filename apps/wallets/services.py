"""
Branch wallet, ledger and withdrawals.

Balance changes: every change locks the wallet row and writes the ledger
entries in the same transaction (call inside atomic()).

Withdrawals: the debit is committed BEFORE the provider is called (an HTTP
call never runs under a database lock). A definite provider rejection
reverses the debit; an unknown outcome (timeout) never does - the withdrawal
stays processing until the callback or the status poll says otherwise.
"""

import datetime
import hashlib
import hmac
import logging
import secrets
import uuid
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.access import get_finance_staff
from apps.core.exceptions import ProviderUnavailable
from apps.core.notes import append_note
from apps.core.webhooks import InvalidWebhook
from apps.mailer.services import Mailer
from apps.payment_aggregator import PaymentAggregator
from apps.payment_aggregator import exceptions as provider_errors
from apps.payment_aggregator.base import TransferRequest, TransferResult, TransferStatus, WithdrawalBreakdown
from apps.payment_aggregator.constants import (
    WITHDRAWAL_OTP_LENGTH,
    WITHDRAWAL_OTP_MAX_ATTEMPTS,
    WITHDRAWAL_OTP_TTL_MINUTES,
)

from . import exceptions as errors
from .models import BranchWallet, LedgerEntry, PayoutAccount, Withdrawal, WithdrawalOtp

logger = logging.getLogger(__name__)



# --- Wallet & ledger ------------------------------------------------------


def lock_wallet(branch_id):
    BranchWallet.objects.get_or_create(branch_id=branch_id)
    return BranchWallet.objects.select_for_update().get(branch_id=branch_id)


def post_payment_credit(gateway_payment):
    """Credit a paid checkout's full invoice total to its branch as PENDING
    settlement (call inside the transaction that marks it paid).

    The whole invoice_total is credited, also for invoices flagged
    needs_refund: the money did arrive, and the school refunds the payer
    itself (manually, in cash). Classping takes no fee of its own.
    """
    wallet = lock_wallet(gateway_payment.branch_id)
    LedgerEntry.objects.create(
        branch_id=gateway_payment.branch_id,
        entry_type=LedgerEntry.EntryType.PAYMENT_CREDIT,
        amount=gateway_payment.invoice_total,
        gateway_payment=gateway_payment,
        settlement_status=LedgerEntry.SettlementStatus.PENDING_SETTLEMENT,
        note=gateway_payment.payment_no,
    )
    wallet.pending_balance += gateway_payment.invoice_total
    wallet.save(update_fields=["pending_balance", "updated_at"])


def mark_payment_settled(gateway_payment, settled_at=None):
    """Provider settled the checkout: pending -> available. Idempotent."""
    settled_at = settled_at or timezone.now()
    with transaction.atomic():
        wallet = lock_wallet(gateway_payment.branch_id)
        entries = list(
            LedgerEntry.objects.select_for_update().filter(
                gateway_payment=gateway_payment,
                settlement_status=LedgerEntry.SettlementStatus.PENDING_SETTLEMENT,
            )
        )
        if not entries:
            return False
        net = sum((entry.amount for entry in entries), Decimal("0"))
        LedgerEntry.objects.filter(pk__in=[entry.pk for entry in entries]).update(
            settlement_status=LedgerEntry.SettlementStatus.SETTLED,
            settled_at=settled_at,
        )
        wallet.pending_balance -= net
        wallet.available_balance += net
        wallet.save(update_fields=["pending_balance", "available_balance", "updated_at"])
    return True


def _post_withdrawal_entries(wallet, withdrawal, entries):
    """``entries``: [(entry_type, signed amount)]; the wallet must be locked."""
    for entry_type, amount in entries:
        LedgerEntry.objects.create(
            branch_id=withdrawal.branch_id,
            entry_type=entry_type,
            amount=amount,
            withdrawal=withdrawal,
            note=withdrawal.withdrawal_no,
        )
        wallet.available_balance += amount
    wallet.save(update_fields=["available_balance", "updated_at"])


def _post_withdrawal_debit(wallet, withdrawal):
    _post_withdrawal_entries(wallet, withdrawal, [
        (LedgerEntry.EntryType.WITHDRAWAL, -withdrawal.transfer_amount),
        (LedgerEntry.EntryType.WITHDRAWAL_FEE, -withdrawal.fee),
    ])


def _post_withdrawal_reversal(withdrawal):
    _post_withdrawal_entries(lock_wallet(withdrawal.branch_id), withdrawal, [
        (LedgerEntry.EntryType.WITHDRAWAL_REVERSAL, withdrawal.transfer_amount),
        (LedgerEntry.EntryType.WITHDRAWAL_FEE_REVERSAL, withdrawal.fee),
    ])


# --- Access & reads -------------------------------------------------------


def get_withdrawal_branch(user):
    """The branch whose wallet ``user`` manages (its principal / officer)."""
    staff = get_finance_staff(user)
    if staff is None:
        raise errors.WithdrawalForbidden()
    return staff.branch


@dataclass(frozen=True)
class WalletSummary:
    branch_id: int
    available_balance: Decimal
    pending_balance: Decimal
    withdrawal_fee: Decimal


def get_wallet_summary(user):
    branch = get_withdrawal_branch(user)
    wallet = BranchWallet.objects.filter(branch=branch).first() or BranchWallet(branch=branch)
    return WalletSummary(
        branch_id=branch.pk,
        available_balance=wallet.available_balance,
        pending_balance=wallet.pending_balance,
        withdrawal_fee=PaymentAggregator.get_withdrawal_rules().fee,
    )


def ledger_queryset(user):
    return LedgerEntry.objects.filter(branch=get_withdrawal_branch(user))


def payout_account_queryset(user):
    return PayoutAccount.objects.filter(branch=get_withdrawal_branch(user))


def withdrawal_queryset(user):
    return Withdrawal.objects.filter(branch=get_withdrawal_branch(user))


# --- Withdrawal preview & OTP ---------------------------------------------


@dataclass(frozen=True)
class WithdrawalPreview:
    otp: WithdrawalOtp
    breakdown: WithdrawalBreakdown


def _calculate_withdrawal(amount):
    try:
        return PaymentAggregator.calculate_withdrawal(amount)
    except provider_errors.AmountBelowMinimum as error:
        raise errors.AmountBelowMinimum(error.message)
    except provider_errors.InvalidAmount as error:
        raise errors.InvalidAmount(error.message)


def _ensure_available_balance(wallet, amount):
    if wallet is None or wallet.available_balance < amount:
        raise errors.InsufficientBalance()


def _resolve_destination(branch, payout_account_id, bank_code, account_number, account_holder_name):
    """A saved payout account of the branch, or a newly entered account."""
    if payout_account_id:
        account = PayoutAccount.objects.filter(branch=branch, pk=payout_account_id).first()
        if account is None:
            raise errors.PayoutAccountNotFound()
        return account.bank_code, account.account_number, account.account_holder_name
    if not (bank_code and account_number and account_holder_name):
        raise errors.PayoutAccountRequired()
    if not PaymentAggregator.is_supported_bank(bank_code):
        raise errors.PayoutBankNotSupported()
    return bank_code, account_number, account_holder_name


def _hash_otp(reference, code):
    message = "{}:{}".format(reference, code).encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def _new_otp_code():
    return "".join(secrets.choice("0123456789") for _ in range(WITHDRAWAL_OTP_LENGTH))


def _otp_expires_at():
    return timezone.now() + datetime.timedelta(minutes=WITHDRAWAL_OTP_TTL_MINUTES)


def preview_withdrawal(user, amount, payout_account_id=None, bank_code="", account_number="", account_holder_name=""):
    """C7: validate, return the breakdown and email an OTP to the branch."""
    branch = get_withdrawal_branch(user)
    if not branch.email:
        raise errors.BranchEmailMissing()
    bank_code, account_number, account_holder_name = _resolve_destination(
        branch, payout_account_id, bank_code, account_number, account_holder_name
    )
    breakdown = _calculate_withdrawal(amount)
    _ensure_available_balance(BranchWallet.objects.filter(branch=branch).first(), breakdown.amount)

    code = _new_otp_code()
    reference = secrets.token_urlsafe(24)
    otp = WithdrawalOtp(
        reference=reference,
        branch=branch,
        user=user,
        amount=breakdown.amount,
        bank_code=bank_code,
        account_number=account_number,
        account_holder_name=account_holder_name,
        code_hash=_hash_otp(reference, code),
        sent_to=branch.email,
        expires_at=_otp_expires_at(),
    )
    # Sent right away (no queue) so a failure is reported to the staff.
    # WhatsApp OTP: not yet (the WhatsApp service is not on this branch).
    try:
        Mailer().send_template(
            to_email=branch.email,
            to_name=branch.name,
            template_id=settings.MAILJET_TEMPLATES["withdrawal_otp"],
            variables={"name": branch.name, "otp": code, "expires_in": WITHDRAWAL_OTP_TTL_MINUTES},
        )
    except Exception:
        logger.exception("Withdrawal OTP email to branch %s failed", branch.pk)
        raise errors.OtpNotSent()
    otp.save()
    return WithdrawalPreview(otp=otp, breakdown=breakdown)


def resend_withdrawal_otp(user, reference):
    """C8: a new OTP (new otp_reference) for the same amount and account;
    the old one stops working."""
    otp = WithdrawalOtp.objects.filter(
        reference=reference, user=user, branch=get_withdrawal_branch(user), used_at__isnull=True
    ).first()
    if otp is None:
        raise errors.OtpExpired()
    preview = preview_withdrawal(
        user,
        otp.amount,
        bank_code=otp.bank_code,
        account_number=otp.account_number,
        account_holder_name=otp.account_holder_name,
    )
    WithdrawalOtp.objects.filter(pk=otp.pk, used_at__isnull=True).update(used_at=timezone.now())
    return preview


def _check_otp(otp, code, now):
    """None when valid; otherwise the error to raise (a wrong code is counted)."""
    if otp is None or now >= otp.expires_at:
        return errors.OtpExpired()
    if otp.attempts >= WITHDRAWAL_OTP_MAX_ATTEMPTS:
        return errors.OtpMaxAttempts()
    if hmac.compare_digest(otp.code_hash, _hash_otp(otp.reference, code)):
        return None
    otp.attempts += 1
    otp.save(update_fields=["attempts"])
    remaining = WITHDRAWAL_OTP_MAX_ATTEMPTS - otp.attempts
    if remaining <= 0:
        return errors.OtpMaxAttempts()
    return errors.OtpInvalid(remaining_attempts=remaining)


# --- Withdrawal -----------------------------------------------------------


def _save_payout_account(user, otp):
    """The account used by a withdrawal is saved for next time."""
    account, created = PayoutAccount.objects.get_or_create(
        branch_id=otp.branch_id,
        bank_code=otp.bank_code,
        account_number=otp.account_number,
        defaults={"account_holder_name": otp.account_holder_name, "created_by": user},
    )
    if not created and account.account_holder_name != otp.account_holder_name:
        account.account_holder_name = otp.account_holder_name
        account.save(update_fields=["account_holder_name", "updated_at"])
    return account


def _create_processing_withdrawal(user, otp, now):
    """Debit the wallet and record the withdrawal (inside atomic())."""
    breakdown = _calculate_withdrawal(otp.amount)
    wallet = lock_wallet(otp.branch_id)
    _ensure_available_balance(wallet, breakdown.amount)

    withdrawal = Withdrawal.objects.create(
        # Replaced below once the id is known (WDR-YYYYMMDD-000123).
        withdrawal_no="TMP-" + uuid.uuid4().hex,
        branch_id=otp.branch_id,
        payout_account=_save_payout_account(user, otp),
        bank_code=otp.bank_code,
        account_number=otp.account_number,
        account_holder_name=otp.account_holder_name,
        amount=breakdown.amount,
        fee=breakdown.fee,
        transfer_amount=breakdown.transfer_amount,
        provider=PaymentAggregator.provider_name(),
        requested_by=user,
        fee_acknowledged_at=now,
    )
    withdrawal.withdrawal_no = "WDR-{:%Y%m%d}-{:06d}".format(timezone.localdate(), withdrawal.pk)
    withdrawal.save(update_fields=["withdrawal_no"])
    _post_withdrawal_debit(wallet, withdrawal)

    otp.used_at = now
    otp.save(update_fields=["used_at"])
    return withdrawal


def create_withdrawal(user, reference, code, fee_acknowledged):
    """C9: verify the OTP, debit the balance, then send the disbursement."""
    if fee_acknowledged is not True:
        raise errors.FeeNotAcknowledged()
    branch = get_withdrawal_branch(user)
    now = timezone.now()
    with transaction.atomic():
        otp = (
            WithdrawalOtp.objects.select_for_update()
            .filter(reference=reference, user=user, branch=branch, used_at__isnull=True)
            .first()
        )
        otp_error = _check_otp(otp, code, now)
        if otp_error is None:
            withdrawal = _create_processing_withdrawal(user, otp, now)
    # Raised after the block so a wrong-code attempt is still counted.
    if otp_error is not None:
        raise otp_error
    return _send_to_provider(withdrawal)


def _send_to_provider(withdrawal):
    request = TransferRequest(
        reference_no=withdrawal.withdrawal_no,
        # The provider deducts its fee from this amount.
        amount=withdrawal.amount,
        bank_code=withdrawal.bank_code,
        account_number=withdrawal.account_number,
        account_name=withdrawal.account_holder_name,
    )
    def rejected(error):
        # Refused before it was processed: fail it and return the balance.
        return TransferResult(
            reference_no=withdrawal.withdrawal_no,
            provider_transfer_id="",
            status=TransferStatus.FAILED,
            provider_message=error.provider_message or error.message,
        )

    try:
        result = PaymentAggregator.transfer_balance(request)
    except provider_errors.DuplicateTransfer:
        # Cannot be told apart from an earlier accepted request: keep it.
        return flag_withdrawal_for_review(withdrawal.pk, "Provider reported a duplicate reference.")
    except provider_errors.InvalidDestinationAccount as error:
        apply_transfer_result(withdrawal.pk, rejected(error))
        raise errors.PayoutAccountInvalid(withdrawal_id=withdrawal.pk)
    except provider_errors.InsufficientProviderBalance as error:
        logger.error("Provider balance insufficient for withdrawal %s", withdrawal.withdrawal_no)
        apply_transfer_result(withdrawal.pk, rejected(error))
        raise errors.ProviderBalanceInsufficient(withdrawal_id=withdrawal.pk)
    except provider_errors.ProviderRejected as error:
        apply_transfer_result(withdrawal.pk, rejected(error))
        raise errors.WithdrawalRejected(withdrawal_id=withdrawal.pk)
    except (provider_errors.ProviderAccessDenied, provider_errors.ProviderNotConfigured) as error:
        logger.error("Withdrawal %s not sent: %s", withdrawal.withdrawal_no, error.message)
        apply_transfer_result(withdrawal.pk, rejected(error))
        raise ProviderUnavailable(
            "The provider refused the request; the balance was returned.", withdrawal_id=withdrawal.pk
        )
    except provider_errors.ProviderUnavailable:
        # Outcome unknown: never reverse; the callback settles it.
        logger.exception("Withdrawal %s outcome unknown", withdrawal.withdrawal_no)
        return flag_withdrawal_for_review(
            withdrawal.pk, "Provider did not answer; waiting for the disbursement callback."
        )

    Withdrawal.objects.filter(pk=withdrawal.pk).update(provider_response=result.raw)
    return apply_transfer_result(withdrawal.pk, result)


def _lock_withdrawal(withdrawal_id):
    return Withdrawal.objects.select_for_update().get(pk=withdrawal_id)


def flag_withdrawal_for_review(withdrawal_id, note):
    with transaction.atomic():
        withdrawal = _lock_withdrawal(withdrawal_id)
        withdrawal.needs_review = True
        withdrawal.review_note = append_note(withdrawal.review_note, note)
        withdrawal.save(update_fields=["needs_review", "review_note", "updated_at"])
    return withdrawal


def apply_transfer_result(withdrawal_id, result):
    """Apply the provider's status (response, callback or poll)."""
    with transaction.atomic():
        withdrawal = _lock_withdrawal(withdrawal_id)
        previous_status = withdrawal.status
        notes = []
        if result.provider_transfer_id and not withdrawal.provider_disbursement_id:
            withdrawal.provider_disbursement_id = result.provider_transfer_id
        if result.provider_status_code:
            withdrawal.provider_status = result.provider_status_code
        if result.fee is not None:
            withdrawal.provider_fee = result.fee
            if result.fee != withdrawal.fee:
                notes.append("Provider fee {} differs from {}.".format(result.fee, withdrawal.fee))
        if result.amount_received is not None and result.amount_received != withdrawal.transfer_amount:
            notes.append(
                "Provider sent {} but {} was expected.".format(result.amount_received, withdrawal.transfer_amount)
            )
        if result.needs_review:
            notes.append("Provider status {} needs review.".format(result.provider_status_code))

        if previous_status == Withdrawal.Status.PROCESSING:
            if result.status == TransferStatus.SUCCESS:
                withdrawal.status = Withdrawal.Status.SUCCESS
                withdrawal.completed_at = timezone.now()
            elif result.status == TransferStatus.FAILED:
                _post_withdrawal_reversal(withdrawal)
                withdrawal.status = Withdrawal.Status.FAILED
                withdrawal.failure_reason = result.provider_message[:255]
                withdrawal.completed_at = timezone.now()
        elif result.status not in (TransferStatus.PROCESSING, previous_status):
            notes.append("Provider reports {} but the withdrawal is {}.".format(result.status, previous_status))

        for note in notes:
            withdrawal.needs_review = True
            withdrawal.review_note = append_note(withdrawal.review_note, note)
        withdrawal.save()

    # success / failed email to the branch; skipped until its template is set.
    template_id = settings.MAILJET_TEMPLATES.get("withdrawal_status")
    if withdrawal.status != previous_status and template_id and withdrawal.branch.email:
        try:
            Mailer().send_template(
                to_email=withdrawal.branch.email,
                to_name=withdrawal.branch.name,
                template_id=template_id,
                variables={
                    "name": withdrawal.branch.name,
                    "withdrawal_no": withdrawal.withdrawal_no,
                    "status": withdrawal.status,
                    "amount": str(withdrawal.amount),
                    "fee": str(withdrawal.fee),
                    "transfer_amount": str(withdrawal.transfer_amount),
                    "bank_name": withdrawal.bank_name,
                    "account_number_masked": withdrawal.account_number_masked,
                    "failure_reason": withdrawal.failure_reason,
                },
            )
        except Exception:
            logger.exception("Withdrawal status email for %s failed", withdrawal.withdrawal_no)
    return withdrawal


def handle_disbursement_callback(raw_body, headers):
    """Webhook ("rintisan", "disbursement")."""
    try:
        result = PaymentAggregator.parse_transfer_callback(raw_body, headers)
    except (provider_errors.InvalidCallback, provider_errors.ProviderNotConfigured) as error:
        logger.warning("Rejected disbursement callback: %s", error)
        raise InvalidWebhook() from error

    withdrawal = None
    if result.reference_no:
        withdrawal = Withdrawal.objects.filter(withdrawal_no=result.reference_no).first()
    if withdrawal is None and result.provider_transfer_id:
        withdrawal = Withdrawal.objects.filter(provider_disbursement_id=result.provider_transfer_id).first()
    if withdrawal is None:
        logger.error("Disbursement callback for unknown withdrawal %s / %s", result.reference_no, result.provider_transfer_id)
        return {"status": "ignored"}

    Withdrawal.objects.filter(pk=withdrawal.pk).update(
        callback_payload=result.raw, callback_received_at=timezone.now()
    )
    apply_transfer_result(withdrawal.pk, result)
    return {"status": "ok"}


def sync_withdrawal(withdrawal_id):
    """Ask the provider for the status (admin "Sync status" and the poll)."""
    withdrawal = Withdrawal.objects.get(pk=withdrawal_id)
    if not withdrawal.provider_disbursement_id:
        return withdrawal
    return apply_transfer_result(
        withdrawal.pk, PaymentAggregator.get_transfer_status(withdrawal.provider_disbursement_id)
    )


def poll_processing_withdrawals():
    """Periodic backup to the callback for processing withdrawals."""
    synced = 0
    processing = Withdrawal.objects.filter(status=Withdrawal.Status.PROCESSING).exclude(
        provider_disbursement_id=""
    ).values_list("pk", flat=True)
    for withdrawal_id in processing:
        try:
            sync_withdrawal(withdrawal_id)
            synced += 1
        except provider_errors.PaymentAggregatorError:
            logger.exception("Status check failed for withdrawal %s", withdrawal_id)
    return synced
