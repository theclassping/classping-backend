import datetime
from decimal import Decimal

import requests
from django.test import SimpleTestCase

from apps.payment_aggregator.base import (
    BillingRequest,
    BillingStatus,
    SettlementStatus,
    TransferRequest,
    TransferStatus,
)
from apps.payment_aggregator.exceptions import (
    BillingNotFound,
    DuplicateBilling,
    DuplicateTransfer,
    InsufficientProviderBalance,
    InvalidAmount,
    InvalidCallback,
    InvalidDestinationAccount,
    ProviderAccessDenied,
    ProviderNotConfigured,
    ProviderRejected,
    ProviderUnavailable,
    TransferAmountOutOfRange,
    TransferNotFound,
)
from apps.payment_aggregator.providers.rintisan import signing
from apps.payment_aggregator.providers.rintisan.config import RintisanConfig
from apps.payment_aggregator.providers.rintisan.provider import RintisanProvider
from apps.payment_aggregator.tests.helpers import (
    CLIENT_ID,
    FakeResponse,
    FakeSession,
    key_pair,
    make_config,
    make_provider,
)

BILLING_REQUEST = BillingRequest(
    reference_no="PAY-20261107-000501",
    channel_code="VABNI",
    amount=Decimal("154000.00"),
    invoice_date=datetime.date(2026, 11, 7),
    deadline_date=datetime.date(2026, 11, 8),
    payer_name="Ibu Sari",
    payer_email="sari@example.com",
    payer_phone="6281234567890",
    note="INV-11, INV-12",
)

TRANSFER_REQUEST = TransferRequest(
    reference_no="WDR-20261107-000012",
    amount=Decimal("1497500.00"),
    bank_code="BCA",
    account_number="5271234567",
    account_name="YAYASAN PENDIDIKAN",
    email="admin@sekolah.sch.id",
)

CREATE_VA_OK = {
    "response_code": "200",
    "message": "Bill details",
    "timestamp": "2026-11-07 10:16:02",
    "partner_trx_id": "PAY-20261107-000501",
    "trx_id": "PPI-261107-7654321FEDCBA",
    "payment_code": "988123456789",
    "total_amount": 154000,
    "payment_method": "VABNI",
    "qr_string": "",
    "payment_link": "",
    "rintisan_billing_link": "https://billing.rintisan.co.id/penagihan/abc",
    "bill_details": [],
}

STATUS_BODY = {
    "timestamp": "2026-11-07 10:35:12",
    "disbursement_id": "DISPTR-261107-12345678",
    "partner_reference_id": "WDR-20261107-000012",
    "amount_request": 1497500,
    "disburse_fee": 2500,
    "disburse_amount": 1497500,
    "bank_code": "BCA",
    "account_number": "5271234567",
    "status": {"code": "200", "message": "success"},
}


def rintisan_sign(raw):
    return signing.sign(CLIENT_ID, raw, key_pair("rintisan")[0])


class RequestSigningTests(SimpleTestCase):
    def test_create_billing_sends_signed_minified_body(self):
        provider, session = make_provider(FakeResponse(body=CREATE_VA_OK))
        provider.create_billing(BILLING_REQUEST)

        call = session.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertTrue(call["url"].endswith("/create"))
        headers = call["headers"]
        self.assertEqual(headers["x-client-id"], CLIENT_ID)
        self.assertEqual(headers["x-api-key"], "api-key")
        # The exact bytes sent are what was signed.
        self.assertTrue(
            signing.verify(CLIENT_ID, call["data"], headers["x-signature"], key_pair("classping")[1])
        )
        self.assertNotIn(b": ", call["data"])

    def test_create_billing_payload(self):
        provider, session = make_provider(FakeResponse(body=CREATE_VA_OK))
        provider.create_billing(BILLING_REQUEST)
        self.assertEqual(
            session.last_json(),
            {
                "partner_trx_id": "PAY-20261107-000501",
                "partner_identifier_id": "PAY-20261107-000501",
                "invoice_date": "2026-11-07",
                "deadline_date": "2026-11-08",
                "to_name": "Ibu Sari",
                "to_address": "",
                "to_phone": "6281234567890",
                # Guardian email is never sent; Rintisan gets Classping's no-reply.
                "to_email": "no-reply@hamanto.com",
                "note": "INV-11, INV-12",
                "payment_method": "VABNI",
                "amount": 154000,
            },
        )

    def test_fractional_amount_rejected_before_sending(self):
        provider, session = make_provider()
        request = BillingRequest(**{**BILLING_REQUEST.__dict__, "amount": Decimal("154000.50")})
        with self.assertRaises(InvalidAmount):
            provider.create_billing(request)
        self.assertEqual(session.calls, [])

    def test_balance_is_unsigned_get(self):
        provider, session = make_provider(
            FakeResponse(body={"response_code": "200", "balance": 5000000, "balance_pending": 250000})
        )
        balance = provider.get_balance()
        self.assertEqual(balance.available, Decimal("5000000"))
        self.assertEqual(balance.pending, Decimal("250000"))
        self.assertEqual(session.calls[0]["method"], "GET")
        self.assertNotIn("x-signature", session.calls[0]["headers"])

    def test_missing_credentials(self):
        provider = RintisanProvider(config=make_config(client_id=""), session=FakeSession())
        with self.assertRaises(ProviderNotConfigured):
            provider.create_billing(BILLING_REQUEST)


class BillingResponseTests(SimpleTestCase):
    def test_create_success_maps_neutral_result(self):
        provider, _ = make_provider(FakeResponse(body=CREATE_VA_OK))
        result = provider.create_billing(BILLING_REQUEST)
        self.assertEqual(result.reference_no, "PAY-20261107-000501")
        self.assertEqual(result.provider_trx_id, "PPI-261107-7654321FEDCBA")
        self.assertEqual(result.status, BillingStatus.PENDING)
        self.assertEqual(result.payment_code, "988123456789")
        self.assertEqual(result.billing_url, "https://billing.rintisan.co.id/penagihan/abc")
        self.assertEqual(result.amount, Decimal("154000"))

    def test_http_200_with_error_response_code(self):
        provider, _ = make_provider(
            FakeResponse(body={"response_code": "400", "message": "Input data tidak lengkap / tidak sesuai."})
        )
        with self.assertRaises(ProviderRejected) as ctx:
            provider.create_billing(BILLING_REQUEST)
        self.assertEqual(ctx.exception.provider_message, "Input data tidak lengkap / tidak sesuai.")

    def test_duplicate_returns_existing_trx_id(self):
        provider, _ = make_provider(
            FakeResponse(body={"response_code": "409", "message": "dup", "trx_id": "PPI-EXISTING"})
        )
        with self.assertRaises(DuplicateBilling) as ctx:
            provider.create_billing(BILLING_REQUEST)
        self.assertEqual(ctx.exception.provider_trx_id, "PPI-EXISTING")

    def test_http_403_is_access_denied(self):
        provider, _ = make_provider(
            FakeResponse(status_code=403, body={"response_code": 403, "message": "Invalid signature"})
        )
        with self.assertRaises(ProviderAccessDenied):
            provider.create_billing(BILLING_REQUEST)

    def test_network_error_and_bad_responses_are_unavailable(self):
        for response in (
            requests.Timeout("timeout"),
            requests.ConnectionError("down"),
            FakeResponse(status_code=502, body=None),
            FakeResponse(status_code=200, body=None),
            FakeResponse(status_code=200, body={"message": "no code"}),
        ):
            provider, _ = make_provider(response)
            with self.assertRaises(ProviderUnavailable, msg=repr(response)):
                provider.create_billing(BILLING_REQUEST)

    def test_query_paid_and_disbursed(self):
        provider, session = make_provider(
            FakeResponse(
                body={
                    **CREATE_VA_OK,
                    "payment_status": "PAID",
                    "disburse_status": "DISBURSED",
                    "paid_at": "2026-11-07 11:45:12",
                }
            )
        )
        result = provider.get_billing_status("PPI-261107-7654321FEDCBA")
        self.assertEqual(session.last_json(), {"trx_id": "PPI-261107-7654321FEDCBA"})
        self.assertEqual(result.status, BillingStatus.PAID)
        self.assertEqual(result.settlement_status, SettlementStatus.SETTLED)
        self.assertEqual(
            result.paid_at,
            datetime.datetime(2026, 11, 7, 4, 45, 12, tzinfo=datetime.timezone.utc),
        )

    def test_query_unpaid_not_disbursed(self):
        provider, _ = make_provider(
            FakeResponse(body={**CREATE_VA_OK, "payment_status": "UNPAID", "disburse_status": "NOT DISBURSED"})
        )
        result = provider.get_billing_status("PPI-1")
        self.assertEqual(result.status, BillingStatus.PENDING)
        self.assertEqual(result.settlement_status, SettlementStatus.NOT_SETTLED)

    def test_query_not_found(self):
        provider, _ = make_provider(FakeResponse(body={"response_code": "400", "message": "Transaction not found."}))
        with self.assertRaises(BillingNotFound):
            provider.get_billing_status("PPI-X")


class TransferTests(SimpleTestCase):
    def test_transfer_payload_and_processing_result(self):
        provider, session = make_provider(
            FakeResponse(
                body={
                    "response_code": "200",
                    "disbursement_id": "DISPTR-261107-12345678",
                    "amount_request": 1497500,
                    "disburse_fee": 2500,
                    "disburse_amount": 1497500,
                }
            )
        )
        result = provider.transfer_balance(TRANSFER_REQUEST)
        self.assertEqual(
            session.last_json(),
            {
                "reference_id": "WDR-20261107-000012",
                "amount": 1497500,
                "name": "YAYASAN PENDIDIKAN",
                "bank_code": "BCA",
                "account_number": "5271234567",
                "email": "admin@sekolah.sch.id",
            },
        )
        self.assertEqual(result.status, TransferStatus.PROCESSING)
        self.assertEqual(result.provider_transfer_id, "DISPTR-261107-12345678")
        self.assertEqual(result.reference_no, "WDR-20261107-000012")
        self.assertEqual(result.fee, Decimal("2500"))

    def test_transfer_business_errors(self):
        cases = {
            "Insufficient balance.": InsufficientProviderBalance,
            "Duplicate reference ID.": DuplicateTransfer,
            "Invalid account number.": InvalidDestinationAccount,
            "Invalid bank code.": InvalidDestinationAccount,
            "Minimum disbursement amount is 20000": TransferAmountOutOfRange,
            "Maximum disbursement amount is 250000000": TransferAmountOutOfRange,
            "Something else": ProviderRejected,
        }
        for message, exc in cases.items():
            provider, _ = make_provider(FakeResponse(body={"response_code": "400", "message": message}))
            with self.assertRaises(exc, msg=message):
                provider.transfer_balance(TRANSFER_REQUEST)

    def test_transfer_timeout_is_unavailable_not_failed(self):
        provider, _ = make_provider(requests.Timeout("timeout"))
        with self.assertRaises(ProviderUnavailable):
            provider.transfer_balance(TRANSFER_REQUEST)

    def test_status_without_response_code_is_parsed(self):
        expectations = {
            "200": (TransferStatus.SUCCESS, False),
            "201": (TransferStatus.PROCESSING, False),
            "202": (TransferStatus.PROCESSING, False),
            "203": (TransferStatus.PROCESSING, False),
            "204": (TransferStatus.PROCESSING, True),
            "400": (TransferStatus.FAILED, False),
            "999": (TransferStatus.PROCESSING, True),
        }
        for code, (status, needs_review) in expectations.items():
            body = {**STATUS_BODY, "status": {"code": code, "message": "x"}}
            provider, session = make_provider(FakeResponse(body=body))
            result = provider.get_transfer_status("DISPTR-261107-12345678")
            self.assertEqual((result.status, result.needs_review), (status, needs_review), msg=code)
            self.assertEqual(result.provider_status_code, code)
        self.assertEqual(session.last_json(), {"disbursement_id": "DISPTR-261107-12345678"})

    def test_status_not_found(self):
        provider, _ = make_provider(FakeResponse(body={"response_code": "400", "message": "Disbursement not found."}))
        with self.assertRaises(TransferNotFound):
            provider.get_transfer_status("DISPTR-X")


class CallbackTests(SimpleTestCase):
    def payment_raw(self):
        return (
            b'{"timestamp":"2026-11-07 10:30:00","paid_at":"2026-11-07 10:35:00",'
            b'"partner_trx_id":"PAY-20261107-000501","trx_id":"PPI-261107-1234567ABCDEF",'
            b'"payment_code":"988123456789","total_amount":154000,'
            b'"status":{"code":"200","message":"success"}}'
        )

    def headers(self, raw, token="callback-token"):
        return {"X-Signature": rintisan_sign(raw), "X-Callback-Token": token}

    def test_valid_payment_callback(self):
        provider, _ = make_provider()
        raw = self.payment_raw()
        result = provider.parse_billing_callback(raw, self.headers(raw))
        self.assertEqual(result.status, BillingStatus.PAID)
        self.assertEqual(result.reference_no, "PAY-20261107-000501")
        self.assertEqual(result.provider_trx_id, "PPI-261107-1234567ABCDEF")
        self.assertEqual(result.amount, Decimal("154000"))
        self.assertIsNotNone(result.paid_at)

    def test_callback_signed_over_unicode_escaped_raw_body(self):
        provider, _ = make_provider()
        raw = b'{"partner_trx_id":"PAY-1","qr_name":"Toko \\u00d1","status":{"code":"200"}}'
        result = provider.parse_billing_callback(raw, self.headers(raw))
        self.assertEqual(result.status, BillingStatus.PAID)

    def test_tampered_payment_callback_rejected(self):
        provider, _ = make_provider()
        raw = self.payment_raw()
        headers = self.headers(raw)
        with self.assertRaises(InvalidCallback):
            provider.parse_billing_callback(raw.replace(b"154000", b"999000"), headers)

    def test_missing_signature_rejected_for_payment(self):
        provider, _ = make_provider()
        with self.assertRaises(InvalidCallback):
            provider.parse_billing_callback(self.payment_raw(), {"x-callback-token": "callback-token"})

    def test_wrong_callback_token_rejected(self):
        provider, _ = make_provider()
        raw = self.payment_raw()
        with self.assertRaises(InvalidCallback):
            provider.parse_billing_callback(raw, self.headers(raw, token="wrong"))

    def test_non_json_body_rejected(self):
        provider, _ = make_provider()
        raw = b"not json"
        with self.assertRaises(InvalidCallback):
            provider.parse_billing_callback(raw, self.headers(raw))

    def test_transfer_callback_failed(self):
        provider, _ = make_provider()
        raw = signing.minify({**STATUS_BODY, "status": {"code": "400", "message": "failed"}}).encode()
        result = provider.parse_transfer_callback(raw, self.headers(raw))
        self.assertEqual(result.status, TransferStatus.FAILED)
        self.assertEqual(result.reference_no, "WDR-20261107-000012")

    def test_unsigned_transfer_callback_depends_on_setting(self):
        raw = signing.minify(STATUS_BODY).encode()
        headers = {"x-callback-token": "callback-token"}

        provider, _ = make_provider()
        with self.assertRaises(InvalidCallback):
            provider.parse_transfer_callback(raw, headers)

        provider, _ = make_provider(require_transfer_callback_signature=False)
        self.assertEqual(provider.parse_transfer_callback(raw, headers).status, TransferStatus.SUCCESS)

        # A signature that is present is always verified.
        with self.assertRaises(InvalidCallback):
            provider.parse_transfer_callback(raw, {**headers, "x-signature": rintisan_sign(b"other")})


class ConfigTests(SimpleTestCase):
    def test_from_env_defaults_to_sandbox(self):
        from unittest import mock

        with mock.patch.dict("os.environ", {"RINTISAN_ENV": ""}, clear=False):
            config = RintisanConfig.from_env()
        self.assertIn("sandbox", config.base_url)

        with mock.patch.dict("os.environ", {"RINTISAN_ENV": "production"}, clear=False):
            config = RintisanConfig.from_env()
        self.assertEqual(config.base_url, "https://api.rintisan.co.id/api/v1/billing/payin/partner")

    def test_payer_email_default_and_override(self):
        from unittest import mock

        with mock.patch.dict("os.environ", {"RINTISAN_PAYER_EMAIL": ""}, clear=False):
            self.assertEqual(RintisanConfig.from_env().payer_email, "no-reply@hamanto.com")
        with mock.patch.dict("os.environ", {"RINTISAN_PAYER_EMAIL": "x@classping.com"}, clear=False):
            self.assertEqual(RintisanConfig.from_env().payer_email, "x@classping.com")
