import base64
import datetime
import hashlib
import hmac
import json
import unittest
from decimal import Decimal

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from payment_aggregator.base import BillingRequest, BillingStatus, TransferRequest, TransferStatus
from payment_aggregator.exceptions import (
    BillingNotFound,
    DuplicateTransfer,
    InsufficientProviderBalance,
    InvalidCallback,
    InvalidDestinationAccount,
    ProviderAccessDenied,
    ProviderNotConfigured,
    ProviderRejected,
    ProviderUnavailable,
    TransferNotFound,
)
from payment_aggregator.providers.doku import signing
from payment_aggregator.testing import (
    DOKU_AGENT_KEY,
    DOKU_CLIENT_ID,
    DOKU_SECRET_KEY,
    FakeResponse,
    doku_notify_headers,
    doku_token_response,
    key_pair,
    make_doku_provider,
)

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 15, 3, 0, tzinfo=UTC)

FEES = {"VIRTUAL_ACCOUNT_BCA": Decimal("4995"), "CREDIT_CARD": Decimal("3.108")}
FLAT_FEES = {"CREDIT_CARD": Decimal("2220")}
NOTIFY_PATH = "/api/webhooks/payment/"


def billing_request(channel="VIRTUAL_ACCOUNT_BCA", **overrides):
    values = dict(
        reference_no="PAY-20261115-000001",
        channel_code=channel,
        amount=Decimal("104995"),
        invoice_date=datetime.date(2026, 11, 15),
        expires_at=NOW + datetime.timedelta(hours=24),
        payer_name="Ibu Sari-Dewi",
        payer_phone="+62 812-3456-7890",
        payer_email="sari@example.com",
    )
    values.update(overrides)
    return BillingRequest(**values)


def transfer_request(**overrides):
    values = dict(
        reference_no="WDR-20261115-000001",
        amount=Decimal("100000"),
        bank_code="BCA",
        account_number="1234512345",
        account_name="Budi Santoso",
    )
    values.update(overrides)
    return TransferRequest(**values)


CHECKOUT_OK = {
    "message": ["SUCCESS"],
    "response": {
        "order": {"amount": "104995", "invoice_number": "PAY-20261115-000001"},
        "payment": {
            "payment_method_types": ["VIRTUAL_ACCOUNT_BCA"],
            "payment_due_date": 1440,
            "token_id": "tok123",
            "url": "https://sandbox.doku.com/checkout-link-v2/tok123",
            "expired_date": "20261116100000",
        },
    },
}

PAID_NOTIFICATION = {
    "service": {"id": "VIRTUAL_ACCOUNT"},
    "acquirer": {"id": "BCA"},
    "channel": {"id": "VIRTUAL_ACCOUNT_BCA"},
    "order": {"invoice_number": "PAY-20261115-000001", "amount": 104995},
    "virtual_account_info": {"virtual_account_number": "1900600000000046"},
    "transaction": {"status": "SUCCESS", "date": "2026-11-15T04:10:00Z", "original_request_id": "r-1"},
}

INQUIRY_OK = {
    "responseCode": "2004200",
    "responseMessage": "Successful",
    "beneficiaryAccountNumber": "1234512345",
    "beneficiaryAccountName": "BUDI SANTOSO",
    "beneficiaryBankCode": "014",
    "sessionId": "SESSION-1",
    "additionalInfo": {"feeAmount": "2500.00", "beneficiaryAmount": "97500.00"},
}
TRANSFER_OK = {
    "responseCode": "2004300",
    "responseMessage": "Successful",
    "referenceNo": "DK0018353",
    "partnerReferenceNo": "WDR-20261115-000001",
}


class SigningTests(unittest.TestCase):
    def test_checkout_signature_matches_documented_algorithm(self):
        body = '{"order":{"invoice_number":"INV-20210124-0001","amount":150000}}'
        expected_components = (
            "Client-Id:MCH-0001-10791114622547\n"
            "Request-Id:cc682442-6c22-493e-8121-b9ef6b3fa728\n"
            "Request-Timestamp:2020-08-11T08:45:42Z\n"
            "Request-Target:/checkout/v1/payment\n"
            "Digest:" + base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
        )
        self.assertEqual(
            signing.checkout_components(
                "MCH-0001-10791114622547", "cc682442-6c22-493e-8121-b9ef6b3fa728",
                "2020-08-11T08:45:42Z", "/checkout/v1/payment", body,
            ),
            expected_components,
        )
        mac = hmac.new(b"secret", expected_components.encode(), hashlib.sha256).digest()
        self.assertEqual(
            signing.checkout_signature(
                "secret", "MCH-0001-10791114622547", "cc682442-6c22-493e-8121-b9ef6b3fa728",
                "2020-08-11T08:45:42Z", "/checkout/v1/payment", body,
            ),
            "HMACSHA256=" + base64.b64encode(mac).decode(),
        )

    def test_get_signature_has_no_digest(self):
        components = signing.checkout_components("c", "r", "t", "/orders/v1/status/INV-1")
        self.assertNotIn("Digest", components)

    def test_snap_string_to_sign(self):
        body = '{"a":1}'
        self.assertEqual(
            signing.snap_string_to_sign("post", "/p", "TOKEN", body, "2026-11-15T10:00:00+07:00"),
            "POST:/p:TOKEN:{}:2026-11-15T10:00:00+07:00".format(hashlib.sha256(body.encode()).hexdigest()),
        )

    def test_token_signature_verifies_with_public_key(self):
        signature = signing.token_signature("client", "2026-11-15T10:00:00+07:00", key_pair("merchant")[0])
        key_pair("merchant")[1].verify(
            base64.b64decode(signature), b"client|2026-11-15T10:00:00+07:00", padding.PKCS1v15(), hashes.SHA256()
        )

    def test_timestamps(self):
        self.assertEqual(signing.utc_timestamp(NOW), "2026-11-15T03:00:00Z")
        self.assertEqual(signing.snap_timestamp(NOW), "2026-11-15T10:00:00+07:00")


class ChannelTests(unittest.TestCase):
    def test_only_channels_with_rates_are_usable(self):
        provider, _ = make_doku_provider(channel_fees=FEES, channel_flat_fees=FLAT_FEES)
        channels = {c.code: c for c in provider.get_channels()}
        self.assertEqual(channels["VIRTUAL_ACCOUNT_BCA"].fee, Decimal("4995"))
        self.assertEqual(channels["CREDIT_CARD"].flat_fee, Decimal("2220"))
        self.assertIsNone(channels["VIRTUAL_ACCOUNT_BNI"].fee)

    def test_unknown_channel_rejected(self):
        with self.assertRaises(ProviderNotConfigured):
            make_doku_provider(channel_fees={"QRIS": Decimal("0.7")})

    def test_banks_use_classping_codes(self):
        provider, _ = make_doku_provider()
        self.assertEqual(provider.get_banks()["BCA"], "BCA")
        self.assertIn("MANDIRI", provider.get_banks())

    def test_withdrawal_rules_need_fee(self):
        provider, _ = make_doku_provider()
        with self.assertRaises(ProviderNotConfigured):
            provider.get_withdrawal_rules()
        provider, _ = make_doku_provider(disbursement_fee=Decimal("2500"))
        self.assertEqual(provider.get_withdrawal_rules().fee, Decimal("2500"))


class CreateBillingTests(unittest.TestCase):
    def test_creates_checkout_for_one_channel(self):
        provider, session = make_doku_provider(FakeResponse(200, CHECKOUT_OK), channel_fees=FEES, now=lambda: NOW)
        result = provider.create_billing(billing_request())

        self.assertEqual(result.payment_link, "https://sandbox.doku.com/checkout-link-v2/tok123")
        self.assertEqual(result.provider_trx_id, "PAY-20261115-000001")
        self.assertEqual(result.status, BillingStatus.PENDING)

        call = session.calls[0]
        self.assertEqual(call["url"], "https://api-sandbox.doku.com/checkout/v1/payment")
        body = session.last_json()
        self.assertEqual(body["order"]["amount"], 104995)
        self.assertEqual(body["order"]["invoice_number"], "PAY-20261115-000001")
        self.assertTrue(body["order"]["auto_redirect"])
        self.assertEqual(body["order"]["callback_url"], "https://app.example.com/payment/finish")
        self.assertEqual(body["payment"]["payment_method_types"], ["VIRTUAL_ACCOUNT_BCA"])
        self.assertEqual(body["payment"]["payment_due_date"], 1440)
        self.assertEqual(body["customer"], {"name": "Ibu Sari Dewi", "phone": "6281234567890", "email": "sari@example.com"})
        self.assertEqual(
            body["additional_info"]["override_notification_url"], "https://api.example.com/api/webhooks/payment/"
        )

        headers = call["headers"]
        expected = signing.checkout_signature(
            DOKU_SECRET_KEY, DOKU_CLIENT_ID, headers["Request-Id"], headers["Request-Timestamp"],
            "/checkout/v1/payment", call["data"].decode(),
        )
        self.assertEqual(headers["Signature"], expected)
        self.assertEqual(headers["Client-Id"], DOKU_CLIENT_ID)

    def test_e_wallet_checkout(self):
        provider, session = make_doku_provider(
            FakeResponse(200, CHECKOUT_OK), channel_fees={"EMONEY_OVO": Decimal("3.5298")}, now=lambda: NOW
        )
        provider.create_billing(billing_request(channel="EMONEY_OVO"))
        self.assertEqual(session.last_json()["payment"]["payment_method_types"], ["EMONEY_OVO"])
        channel = {c.code: c for c in provider.get_channels()}["EMONEY_OVO"]
        self.assertEqual(channel.method, "e_wallet")

    def test_due_date_rounds_up_and_has_a_minimum(self):
        provider, session = make_doku_provider(
            FakeResponse(200, CHECKOUT_OK), FakeResponse(200, CHECKOUT_OK), now=lambda: NOW
        )
        provider.create_billing(billing_request(expires_at=NOW + datetime.timedelta(seconds=61)))
        self.assertEqual(session.last_json()["payment"]["payment_due_date"], 2)
        provider.create_billing(billing_request(expires_at=NOW - datetime.timedelta(minutes=5)))
        self.assertEqual(session.last_json()["payment"]["payment_due_date"], 1)

    def test_validation_error_is_rejected(self):
        provider, _ = make_doku_provider(
            FakeResponse(400, {"error_messages": ["order.invoice_number must be filled"]}), now=lambda: NOW
        )
        with self.assertRaises(ProviderRejected) as ctx:
            provider.create_billing(billing_request())
        self.assertIn("invoice_number", ctx.exception.provider_message)

    def test_server_error_is_unavailable(self):
        provider, _ = make_doku_provider(FakeResponse(503, None, text="down"), now=lambda: NOW)
        with self.assertRaises(ProviderUnavailable):
            provider.create_billing(billing_request())

    def test_network_error_is_unavailable(self):
        provider, _ = make_doku_provider(requests.ConnectionError("boom"), now=lambda: NOW)
        with self.assertRaises(ProviderUnavailable):
            provider.create_billing(billing_request())

    def test_long_reference_rejected_before_sending(self):
        provider, session = make_doku_provider(now=lambda: NOW)
        with self.assertRaises(ProviderRejected):
            provider.create_billing(billing_request(reference_no="X" * 31))
        self.assertEqual(session.calls, [])

    def test_missing_credentials(self):
        provider, _ = make_doku_provider(secret_key="")
        with self.assertRaises(ProviderNotConfigured):
            provider.create_billing(billing_request())


class BillingStatusTests(unittest.TestCase):
    def test_paid(self):
        provider, session = make_doku_provider(FakeResponse(200, PAID_NOTIFICATION))
        result = provider.get_billing_status("PAY-20261115-000001")
        self.assertEqual(result.status, BillingStatus.PAID)
        self.assertEqual(result.paid_at, datetime.datetime(2026, 11, 15, 4, 10, tzinfo=UTC))
        self.assertEqual(result.amount, Decimal("104995"))
        self.assertEqual(result.payment_code, "1900600000000046")
        call = session.calls[0]
        self.assertEqual(call["method"], "GET")
        self.assertEqual(call["url"], "https://api-sandbox.doku.com/orders/v1/status/PAY-20261115-000001")
        self.assertNotIn("data", call)

    def test_pending_failed_and_expired_stay_pending(self):
        for status in ("PENDING", "FAILED", "EXPIRED"):
            body = dict(PAID_NOTIFICATION, transaction={"status": status})
            provider, _ = make_doku_provider(FakeResponse(200, body))
            result = provider.get_billing_status("PAY-1")
            self.assertEqual(result.status, BillingStatus.PENDING, status)
            self.assertIsNone(result.paid_at)

    def test_not_found(self):
        provider, _ = make_doku_provider(FakeResponse(404, {"error": {"message": "not found"}}))
        with self.assertRaises(BillingNotFound):
            provider.get_billing_status("PAY-1")

    def test_access_denied(self):
        provider, _ = make_doku_provider(FakeResponse(401, {"error": "Invalid signature"}))
        with self.assertRaises(ProviderAccessDenied):
            provider.get_billing_status("PAY-1")


class PaymentCallbackTests(unittest.TestCase):
    def setUp(self):
        self.provider, _ = make_doku_provider()
        self.raw = json.dumps(PAID_NOTIFICATION).encode()

    def test_valid_notification(self):
        result = self.provider.parse_billing_callback(
            self.raw, doku_notify_headers(NOTIFY_PATH, self.raw), request_path=NOTIFY_PATH
        )
        self.assertEqual(result.reference_no, "PAY-20261115-000001")
        self.assertEqual(result.status, BillingStatus.PAID)
        self.assertIsNone(self.provider.callback_reply("payment", result))

    def test_signature_over_another_path_rejected(self):
        with self.assertRaises(InvalidCallback):
            self.provider.parse_billing_callback(
                self.raw, doku_notify_headers("/other/", self.raw), request_path=NOTIFY_PATH
            )

    def test_tampered_body_rejected(self):
        headers = doku_notify_headers(NOTIFY_PATH, self.raw)
        tampered = self.raw.replace(b"104995", b"999999")
        with self.assertRaises(InvalidCallback):
            self.provider.parse_billing_callback(tampered, headers, request_path=NOTIFY_PATH)

    def test_wrong_secret_or_client_rejected(self):
        with self.assertRaises(InvalidCallback):
            self.provider.parse_billing_callback(
                self.raw, doku_notify_headers(NOTIFY_PATH, self.raw, secret_key="other"), request_path=NOTIFY_PATH
            )
        with self.assertRaises(InvalidCallback):
            self.provider.parse_billing_callback(
                self.raw, doku_notify_headers(NOTIFY_PATH, self.raw, client_id="other"), request_path=NOTIFY_PATH
            )

    def test_other_providers_rejected_cheaply(self):
        with self.assertRaises(InvalidCallback):
            self.provider.parse_billing_callback(self.raw, {"X-SIGNATURE": "abc", "X-TIMESTAMP": "t"})


class TransferTests(unittest.TestCase):
    def provider(self, *responses, **overrides):
        return make_doku_provider(*responses, disbursement_fee=Decimal("2500"), **overrides)

    def test_inquiry_then_transfer(self):
        provider, session = self.provider(
            doku_token_response(), FakeResponse(200, INQUIRY_OK), FakeResponse(200, TRANSFER_OK)
        )
        result = provider.transfer_balance(transfer_request())

        self.assertEqual(result.status, TransferStatus.SUCCESS)
        self.assertEqual(result.provider_transfer_id, "WDR-20261115-000001|014|1234512345")
        self.assertEqual(result.fee, Decimal("2500.00"))
        self.assertEqual(result.amount_received, Decimal("97500"))

        token_call, inquiry_call, transfer_call = session.calls
        self.assertTrue(token_call["url"].endswith("/authorization/v1/access-token/b2b"))
        self.assertEqual(token_call["headers"]["X-CLIENT-KEY"], DOKU_CLIENT_ID)

        inquiry = json.loads(inquiry_call["data"])
        self.assertEqual(inquiry["beneficiaryBankCode"], "014")
        self.assertEqual(inquiry["amount"], {"value": "97500.00", "currency": "IDR"})
        self.assertEqual(inquiry["additionalInfo"]["senderCountryCode"], "ID")

        transfer = json.loads(transfer_call["data"])
        self.assertEqual(transfer["sessionId"], "SESSION-1")
        self.assertEqual(transfer["partnerReferenceNo"], "WDR-20261115-000001")
        self.assertEqual(transfer["amount"]["value"], "97500.00")
        info = transfer["additionalInfo"]
        self.assertEqual((info["beneficiaryFirstName"], info["beneficiaryLastName"]), ("BUDI", "SANTOSO"))
        self.assertEqual(info["beneficiaryPhoneNumber"], "6281200000000")
        self.assertEqual(info["senderPersonalIdType"], "KTP")
        self.assertNotIn("channelCode", info)

        headers = transfer_call["headers"]
        self.assertEqual(headers["Authorization"], "Bearer token-abc")
        self.assertTrue(headers["X-EXTERNAL-ID"].isdigit())
        self.assertEqual(
            headers["X-SIGNATURE"],
            signing.snap_signature(
                DOKU_SECRET_KEY, "POST", "/snap/v1.1/emoney/transfer-bank", "token-abc",
                transfer_call["data"].decode(), headers["X-TIMESTAMP"],
            ),
        )

    def test_token_is_reused(self):
        provider, session = self.provider(
            doku_token_response(), FakeResponse(200, INQUIRY_OK), FakeResponse(200, TRANSFER_OK),
            FakeResponse(200, INQUIRY_OK), FakeResponse(200, TRANSFER_OK),
        )
        provider.transfer_balance(transfer_request())
        provider.transfer_balance(transfer_request(reference_no="WDR-2"))
        self.assertEqual(len(session.calls), 5)

    def test_rejected_token_is_renewed_once(self):
        provider, session = self.provider(
            doku_token_response(),
            FakeResponse(401, {"responseCode": "4014201", "responseMessage": "Invalid Token (B2B)"}),
            doku_token_response(), FakeResponse(200, INQUIRY_OK), FakeResponse(200, TRANSFER_OK),
        )
        self.assertEqual(provider.transfer_balance(transfer_request()).status, TransferStatus.SUCCESS)

    def test_pending_transfer(self):
        provider, _ = self.provider(
            doku_token_response(), FakeResponse(200, INQUIRY_OK),
            FakeResponse(202, {"responseCode": "2024300", "responseMessage": "Transaction still on process"}),
        )
        result = provider.transfer_balance(transfer_request())
        self.assertEqual(result.status, TransferStatus.PROCESSING)
        self.assertTrue(result.provider_transfer_id)

    def test_business_errors(self):
        cases = {
            "4034314": InsufficientProviderBalance,
            "4044311": InvalidDestinationAccount,
            "4094301": DuplicateTransfer,
            "4034303": ProviderRejected,
            "5004301": ProviderUnavailable,
            "5044300": ProviderUnavailable,
        }
        for code, error in cases.items():
            provider, _ = self.provider(
                doku_token_response(), FakeResponse(200, INQUIRY_OK),
                FakeResponse(400, {"responseCode": code, "responseMessage": "x"}),
            )
            with self.assertRaises(error, msg=code):
                provider.transfer_balance(transfer_request())

    def test_inquiry_failures_send_nothing(self):
        provider, session = self.provider(
            doku_token_response(), FakeResponse(404, {"responseCode": "4044211", "responseMessage": "Invalid Account"})
        )
        with self.assertRaises(InvalidDestinationAccount):
            provider.transfer_balance(transfer_request())
        self.assertEqual(len(session.calls), 2)

        provider, _ = self.provider(doku_token_response(), requests.Timeout("slow"))
        with self.assertRaises(ProviderRejected) as ctx:
            provider.transfer_balance(transfer_request())
        self.assertNotIsInstance(ctx.exception, ProviderUnavailable)

    def test_transfer_timeout_is_unknown(self):
        provider, _ = self.provider(doku_token_response(), FakeResponse(200, INQUIRY_OK), requests.Timeout("slow"))
        with self.assertRaises(ProviderUnavailable):
            provider.transfer_balance(transfer_request())

    def test_unsupported_bank(self):
        provider, session = self.provider()
        with self.assertRaises(InvalidDestinationAccount):
            provider.transfer_balance(transfer_request(bank_code="GOPAY"))
        self.assertEqual(session.calls, [])

    def test_sender_identity_required(self):
        provider, _ = self.provider(sender_id_number="")
        with self.assertRaises(ProviderNotConfigured):
            provider.transfer_balance(transfer_request())

    def test_channel_code_sent_when_configured(self):
        provider, session = self.provider(
            doku_token_response(), FakeResponse(200, INQUIRY_OK), FakeResponse(200, TRANSFER_OK),
            payout_channel_code="11",
        )
        provider.transfer_balance(transfer_request())
        self.assertEqual(session.last_json()["additionalInfo"]["channelCode"], "11")

    def test_token_refused(self):
        provider, _ = self.provider(FakeResponse(401, {"responseCode": "4017300", "responseMessage": "Unauthorized. Signature"}))
        with self.assertRaises(ProviderAccessDenied):
            provider.transfer_balance(transfer_request())


class TransferStatusTests(unittest.TestCase):
    TRANSFER_ID = "WDR-20261115-000001|014|1234512345"

    def status(self, latest):
        provider, session = make_doku_provider(
            doku_token_response(),
            FakeResponse(200, {
                "responseCode": "2005300", "responseMessage": "Successful",
                "originalPartnerReferenceNo": "WDR-20261115-000001", "latestTransactionStatus": latest,
            }),
        )
        return provider.get_transfer_status(self.TRANSFER_ID), session

    def test_status_mapping(self):
        expected = {"00": TransferStatus.SUCCESS, "03": TransferStatus.PROCESSING,
                    "04": TransferStatus.FAILED, "06": TransferStatus.FAILED}
        for latest, status in expected.items():
            self.assertEqual(self.status(latest)[0].status, status, latest)

    def test_request_carries_bank_and_account(self):
        _, session = self.status("00")
        self.assertEqual(session.last_json(), {
            "originalPartnerReferenceNo": "WDR-20261115-000001",
            "serviceCode": "43",
            "beneficiaryAccountNumber": "1234512345",
            "beneficiaryBankCode": "014",
        })

    def test_unknown_status_needs_review(self):
        result, _ = self.status("99")
        self.assertEqual(result.status, TransferStatus.PROCESSING)
        self.assertTrue(result.needs_review)

    def test_not_found(self):
        provider, _ = make_doku_provider(
            doku_token_response(), FakeResponse(404, {"responseCode": "4045301", "responseMessage": "Not Found"})
        )
        with self.assertRaises(TransferNotFound):
            provider.get_transfer_status(self.TRANSFER_ID)

    def test_malformed_id(self):
        provider, _ = make_doku_provider()
        with self.assertRaises(TransferNotFound):
            provider.get_transfer_status("DK0018353")


class TransferCallbackTests(unittest.TestCase):
    def headers(self, agent_key=DOKU_AGENT_KEY):
        return {"requestId": "req-1", "agentKey": agent_key, "signature": "x", "Content-Type": "application/json"}

    def body(self, **fields):
        values = {
            "sendTrxId": "WDR-20261115-000001", "transactionId": "DK0018353", "invoiceNumber": "I0887",
            "transactionStatus": "50", "activityCode": "200", "message": "Transaction is Success",
            "processDate": "2026-11-15T07:30:12", "createdTime": "1699520040340",
        }
        values.update(fields)
        return json.dumps(values).encode()

    def test_unpaid_to_success(self):
        provider, _ = make_doku_provider()
        result = provider.parse_transfer_callback(self.body(), self.headers())
        self.assertEqual(result.reference_no, "WDR-20261115-000001")
        self.assertEqual(result.status, TransferStatus.SUCCESS)
        body, headers = provider.callback_reply("disbursement", result)
        self.assertEqual(body, {"responseCode": "00", "responseMessage": "Successfully processed",
                                "status": True, "transactionId": "DK0018353"})

    def test_failed_and_refund(self):
        provider, _ = make_doku_provider()
        self.assertEqual(
            provider.parse_transfer_callback(self.body(transactionStatus="35"), self.headers()).status,
            TransferStatus.FAILED,
        )
        refund = json.dumps({"transactionId": "DK1", "activityCode": "200", "message": "Transaction is Refunded",
                             "processDate": "2026-11-15T07:30:12"}).encode()
        self.assertEqual(provider.parse_transfer_callback(refund, self.headers()).status, TransferStatus.FAILED)

    def test_wrong_agent_key_rejected(self):
        provider, _ = make_doku_provider()
        with self.assertRaises(InvalidCallback):
            provider.parse_transfer_callback(self.body(), self.headers(agent_key="nope"))

    def test_agent_key_must_be_configured(self):
        provider, _ = make_doku_provider(payout_agent_key="")
        with self.assertRaises(ProviderNotConfigured):
            provider.parse_transfer_callback(self.body(), self.headers())

    def test_other_providers_rejected(self):
        provider, _ = make_doku_provider()
        with self.assertRaises(InvalidCallback):
            provider.parse_transfer_callback(self.body(), {"X-SIGNATURE": "a"})

    def test_reference_fallback_and_echoed_beneficiary(self):
        provider, _ = make_doku_provider()
        body = json.loads(self.body())
        del body["sendTrxId"]
        body.update(partnerReferenceNo="WDR-20261115-000001", beneficiaryBankCode="014",
                    beneficiaryAccountNumber="1234512345")
        result = provider.parse_transfer_callback(json.dumps(body).encode(), self.headers())
        self.assertEqual(result.reference_no, "WDR-20261115-000001")
        # Same id as the transfer response / transfer_id_for, so it matches provider_disbursement_id.
        self.assertEqual(result.provider_transfer_id, provider.transfer_id_for(transfer_request()))

    def test_callbacks_need_confirmation(self):
        provider, _ = make_doku_provider()
        self.assertTrue(provider.confirm_transfer_callbacks)


class TransferIdTests(unittest.TestCase):
    def test_derived_from_request(self):
        provider, _ = make_doku_provider()
        self.assertEqual(provider.transfer_id_for(transfer_request()), "WDR-20261115-000001|014|1234512345")

    def test_unknown_bank_has_none(self):
        provider, _ = make_doku_provider()
        self.assertIsNone(provider.transfer_id_for(transfer_request(bank_code="NOPE")))


class BalanceTests(unittest.TestCase):
    def test_balance(self):
        provider, session = make_doku_provider(
            doku_token_response(),
            FakeResponse(200, {
                "responseCode": "2001100", "responseMessage": "Successful", "accountNo": "1000000001",
                "accountInfos": {"avaliableBalance": {"value": "5000000.00", "currency": "IDR"},
                                 "holdAmount": {"value": "25000.00", "currency": "IDR"}},
            }),
        )
        balance = provider.get_balance()
        self.assertEqual(balance.available, Decimal("5000000.00"))
        self.assertEqual(balance.pending, Decimal("25000.00"))
        self.assertEqual(session.last_json(), {"accountNo": "1000000001"})

    def test_account_required(self):
        provider, _ = make_doku_provider(payout_account_no="")
        with self.assertRaises(ProviderNotConfigured):
            provider.get_balance()
