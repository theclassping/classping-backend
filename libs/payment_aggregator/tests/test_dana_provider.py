import datetime
import hashlib
import json
import unittest
from decimal import Decimal

import requests

from payment_aggregator.base import BillingRequest, BillingStatus, RefundRequest, RefundStatus, SettlementStatus
from payment_aggregator.exceptions import (
    BillingNotCancellable,
    BillingNotFound,
    InvalidAmount,
    RefundRejected,
    InvalidCallback,
    InvalidPayerPhone,
    ProviderAccessDenied,
    ProviderNotConfigured,
    ProviderRejected,
    ProviderUnavailable,
)
from payment_aggregator.providers.dana import constants, signing
from payment_aggregator.testing import (
    DANA_PARTNER_ID,
    FakeResponse,
    dana_notify_headers,
    key_pair,
    make_dana_provider,
)

WIB = datetime.timezone(datetime.timedelta(hours=7))

FEES = {"VIRTUAL_ACCOUNT_BCA": Decimal("2775"), "NETWORK_PAY_PG_CARD": Decimal("3.219")}


def billing_request(channel="VIRTUAL_ACCOUNT_BCA", **overrides):
    values = dict(
        reference_no="PAY-20261112-000001",
        channel_code=channel,
        amount=Decimal("127775"),
        invoice_date=datetime.date(2026, 11, 12),
        expires_at=datetime.datetime(2026, 11, 12, 4, 30, tzinfo=datetime.timezone.utc),
        payer_name="Ibu Sari",
        payer_phone="6281234567890",
        note="INV-1, INV-2",
    )
    values.update(overrides)
    return BillingRequest(**values)


CREATE_OK = {
    "responseCode": "2005400",
    "responseMessage": "Successful",
    "referenceNo": "2026111211212800100166",
    "partnerReferenceNo": "PAY-20261112-000001",
    "additionalInfo": {"paymentCode": "8808123456789"},
}


class SigningTests(unittest.TestCase):
    def test_string_to_sign_matches_dana_documentation(self):
        body = (
            '{"partnerReferenceNo":"2020102900000000000001","balanceTypes":["BALANCE"],'
            '"additionalInfo":{"accessToken":"fa8sjjEj813Y9JGoqwOeOPWbnt4CUpvIJbU1mMU4a11MNDZ7Sg5u9a"}}'
        )
        expected_hash = hashlib.sha256(body.encode()).hexdigest()
        self.assertEqual(
            signing.string_to_sign("post", "/v1.0/balance-inquiry.htm", body, "2022-11-30T09:45:35+07:00"),
            "POST:/v1.0/balance-inquiry.htm:{}:2022-11-30T09:45:35+07:00".format(expected_hash),
        )

    def test_sign_then_verify(self):
        signature = signing.sign("POST", "/p", "{}", "t", key_pair("dana")[0])
        self.assertTrue(signing.verify("POST", ["/p"], b"{}", "t", signature, key_pair("dana")[1]))
        self.assertFalse(signing.verify("POST", ["/other"], b"{}", "t", signature, key_pair("dana")[1]))

    def test_keys_load_from_pem_or_raw_base64(self):
        from cryptography.hazmat.primitives import serialization

        private, public = key_pair("merchant")
        pkcs8_pem = private.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        pkcs1_der = private.private_bytes(
            serialization.Encoding.DER, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()
        )
        spki_der = public.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        raw_pkcs8 = b"".join(line for line in pkcs8_pem.splitlines() if not line.startswith(b"-----"))
        import base64

        for key in (pkcs8_pem, raw_pkcs8, base64.b64encode(pkcs1_der)):
            loaded = signing.load_private_key(key)
            self.assertEqual(loaded.private_numbers(), private.private_numbers())
        loaded_public = signing.load_public_key(base64.b64encode(spki_der))
        self.assertEqual(loaded_public.public_numbers(), public.public_numbers())
        with self.assertRaises(ValueError):
            signing.load_private_key(b"not a key!")

    def test_timestamp_is_jakarta_time(self):
        now = datetime.datetime(2026, 11, 12, 3, 4, 5, tzinfo=datetime.timezone.utc)
        self.assertEqual(signing.timestamp(now), "2026-11-12T10:04:05+07:00")


class CreateOrderTests(unittest.TestCase):
    def test_virtual_account_order(self):
        provider, session = make_dana_provider(FakeResponse(body=CREATE_OK), channel_fees=FEES)
        result = provider.create_billing(billing_request())

        self.assertEqual(result.provider_trx_id, "2026111211212800100166")
        self.assertEqual(result.payment_code, "8808123456789")
        self.assertEqual(result.status, BillingStatus.PENDING)

        call = session.calls[0]
        self.assertEqual(call["url"], "https://api.sandbox.dana.id" + constants.PATH_CREATE_ORDER)
        payload = session.last_json()
        self.assertEqual(payload["amount"], {"value": "127775.00", "currency": "IDR"})
        self.assertEqual(payload["validUpTo"], "2026-11-12T11:30:00+07:00")
        self.assertEqual(payload["payOptionDetails"][0]["payMethod"], "VIRTUAL_ACCOUNT")
        self.assertEqual(payload["payOptionDetails"][0]["payOption"], "VIRTUAL_ACCOUNT_BCA")
        self.assertNotIn("additionalInfo", payload["payOptionDetails"][0])
        self.assertEqual(
            payload["urlParams"],
            [
                {"url": "https://api.example.com/api/webhooks/payment/", "type": "NOTIFICATION", "isDeeplink": "N"},
                {"url": "https://app.example.com/payment/finish", "type": "PAY_RETURN", "isDeeplink": "N"},
            ],
        )
        self.assertEqual(payload["additionalInfo"]["order"], {"orderTitle": "INV-1, INV-2", "scenario": "API"})
        self.assertEqual(payload["additionalInfo"]["mcc"], "8211")

        headers = call["headers"]
        self.assertEqual(headers["X-PARTNER-ID"], DANA_PARTNER_ID)
        self.assertEqual(headers["CHANNEL-ID"], "95221")
        self.assertLessEqual(len(headers["X-EXTERNAL-ID"]), 36)
        self.assertTrue(
            signing.verify(
                "POST",
                [constants.PATH_CREATE_ORDER],
                call["data"],
                headers["X-TIMESTAMP"],
                headers["X-SIGNATURE"],
                key_pair("merchant")[1],
            )
        )

    def test_card_order_sends_phone_and_returns_redirect_link(self):
        body = dict(CREATE_OK, webRedirectUrl="https://m.sandbox.dana.id/pay?x=1", additionalInfo={})
        provider, session = make_dana_provider(FakeResponse(body=body), channel_fees=FEES)
        result = provider.create_billing(billing_request("NETWORK_PAY_PG_CARD"))
        option = session.last_json()["payOptionDetails"][0]
        self.assertEqual(option["payMethod"], "CREDIT_CARD")
        self.assertEqual(option["payOption"], "NETWORK_PAY_PG_CARD")
        self.assertEqual(option["additionalInfo"], {"phoneNumber": "6281234567890"})
        self.assertEqual(result.payment_link, "https://m.sandbox.dana.id/pay?x=1")

    def test_card_order_rejects_non_indonesian_phone_before_sending(self):
        provider, session = make_dana_provider(channel_fees=FEES)
        with self.assertRaises(InvalidPayerPhone):
            provider.create_billing(billing_request("NETWORK_PAY_PG_CARD", payer_phone="081234"))
        self.assertEqual(session.calls, [])

    def test_error_codes(self):
        cases = [
            ({"responseCode": "4045418", "responseMessage": "Inconsistent Request"}, ProviderRejected),
            ({"responseCode": "4005402", "responseMessage": "Invalid Mandatory Field"}, ProviderRejected),
            ({"responseCode": "4015400", "responseMessage": "Unauthorized. Invalid Signature"}, ProviderAccessDenied),
            ({"responseCode": "5005401", "responseMessage": "Internal Server Error"}, ProviderUnavailable),
            ({"responseCode": "4295400", "responseMessage": "Too Many Requests"}, ProviderUnavailable),
            ({"responseCode": "2025400", "responseMessage": "Request In Progress"}, ProviderUnavailable),
        ]
        for body, error in cases:
            with self.subTest(code=body["responseCode"]):
                provider, _ = make_dana_provider(FakeResponse(status_code=400, body=body), channel_fees=FEES)
                with self.assertRaises(error):
                    provider.create_billing(billing_request())

    def test_transport_failures_are_unavailable(self):
        for response in (FakeResponse(status_code=502, text="Bad Gateway"), requests.Timeout("slow")):
            provider, _ = make_dana_provider(response, channel_fees=FEES)
            with self.assertRaises(ProviderUnavailable):
                provider.create_billing(billing_request())

    def test_missing_settings_are_named(self):
        provider, session = make_dana_provider(channel_fees=FEES, channel_id="", notify_url="")
        with self.assertRaisesMessage(ProviderNotConfigured, "DANA_NOTIFY_URL"):
            provider.create_billing(billing_request())
        provider, session = make_dana_provider(channel_fees=FEES, channel_id="")
        with self.assertRaisesMessage(ProviderNotConfigured, "DANA_CHANNEL_ID"):
            provider.create_billing(billing_request())
        self.assertEqual(session.calls, [])

    def test_channel_id_defaults_to_sdk_value(self):
        import os
        from unittest import mock

        from payment_aggregator.providers.dana import DanaConfig

        with mock.patch.dict(os.environ, {"DANA_CHANNEL_ID": ""}, clear=True):
            self.assertEqual(DanaConfig.from_env().channel_id, "95221")
        with mock.patch.dict(os.environ, {"DANA_CHANNEL_ID": "12345"}, clear=True):
            self.assertEqual(DanaConfig.from_env().channel_id, "12345")

    def assertRaisesMessage(self, error, text):
        return self.assertRaisesRegex(error, text)


def query_body(status, **extra):
    body = {
        "responseCode": "2005500",
        "responseMessage": "Successful",
        "originalPartnerReferenceNo": "PAY-20261112-000001",
        "originalReferenceNo": "2026111211212800100166",
        "serviceCode": "54",
        "latestTransactionStatus": status,
        "amount": {"value": "127775.00", "currency": "IDR"},
    }
    body.update(extra)
    return body


class QueryPaymentTests(unittest.TestCase):
    def query(self, body, status_code=200):
        provider, session = make_dana_provider(FakeResponse(status_code=status_code, body=body))
        return provider.get_billing_status("2026111211212800100166"), session

    def test_paid(self):
        result, session = self.query(query_body("00", paidTime="2026-11-12T10:41:00+07:00"))
        self.assertEqual(result.status, BillingStatus.PAID)
        self.assertEqual(result.amount, Decimal("127775.00"))
        self.assertEqual(result.paid_at, datetime.datetime(2026, 11, 12, 10, 41, tzinfo=WIB))
        self.assertEqual(result.settlement_status, SettlementStatus.NOT_SETTLED)
        self.assertEqual(
            session.last_json(),
            {"originalReferenceNo": "2026111211212800100166", "serviceCode": "54", "merchantId": "216620000000000000000"},
        )

    def test_paying_counts_as_paid(self):
        self.assertEqual(self.query(query_body("02"))[0].status, BillingStatus.PAID)

    def test_waiting_and_cancelled_stay_pending(self):
        for status in ("01", "05"):
            with self.subTest(status=status):
                result = self.query(query_body(status))[0]
                self.assertEqual(result.status, BillingStatus.PENDING)
                self.assertIsNone(result.paid_at)

    def test_not_found(self):
        with self.assertRaises(BillingNotFound):
            self.query(query_body("07"))
        with self.assertRaises(BillingNotFound):
            self.query({"responseCode": "4045501", "responseMessage": "Transaction Not Found"}, status_code=404)

    def test_failed_query_is_unavailable(self):
        with self.assertRaises(ProviderUnavailable):
            self.query({"responseCode": "5005500", "responseMessage": "General Error"}, status_code=500)


NOTIFY = {
    "originalPartnerReferenceNo": "PAY-20261112-000001",
    "originalReferenceNo": "2026111211212800100166",
    "merchantId": "216620000000000000000",
    "amount": {"value": "127775.00", "currency": "IDR"},
    "latestTransactionStatus": "00",
    "transactionStatusDesc": "success",
    "createdTime": "2026-11-12T10:30:00+07:00",
    "finishedTime": "2026-11-12T10:41:05+07:00",
    "additionalInfo": {"paymentInfo": {"paidTime": "2026-11-12T10:41:00+07:00", "payOptionInfos": []}},
}
OUR_PATH = "/api/webhooks/payment/"


class FinishNotifyTests(unittest.TestCase):
    def setUp(self):
        self.provider, _ = make_dana_provider()

    def parse(self, raw, headers, path=OUR_PATH):
        return self.provider.parse_billing_callback(raw, headers, request_path=path)

    def test_paid_notification_signed_over_our_path(self):
        raw = json.dumps(NOTIFY, separators=(",", ":")).encode()
        result = self.parse(raw, dana_notify_headers(OUR_PATH, raw))
        self.assertEqual(result.reference_no, "PAY-20261112-000001")
        self.assertEqual(result.provider_trx_id, "2026111211212800100166")
        self.assertEqual(result.status, BillingStatus.PAID)
        self.assertEqual(result.amount, Decimal("127775.00"))
        self.assertEqual(result.paid_at, datetime.datetime(2026, 11, 12, 10, 41, tzinfo=WIB))

    def test_signed_over_snap_standard_path_is_accepted(self):
        raw = json.dumps(NOTIFY).encode()
        result = self.parse(raw, dana_notify_headers(constants.SNAP_PATH_FINISH_NOTIFY, raw))
        self.assertEqual(result.status, BillingStatus.PAID)

    def test_pretty_printed_body_verifies_against_minified_signature(self):
        raw = json.dumps(NOTIFY, indent=2).encode()
        self.assertEqual(self.parse(raw, dana_notify_headers(OUR_PATH, raw)).status, BillingStatus.PAID)

    def test_expired_notification_is_pending(self):
        raw = json.dumps(dict(NOTIFY, latestTransactionStatus="05")).encode()
        result = self.parse(raw, dana_notify_headers(OUR_PATH, raw))
        self.assertEqual(result.status, BillingStatus.PENDING)
        self.assertIsNone(result.paid_at)

    def test_rejections(self):
        raw = json.dumps(NOTIFY).encode()
        tampered = json.dumps(dict(NOTIFY, amount={"value": "1.00", "currency": "IDR"})).encode()
        with self.assertRaises(InvalidCallback):
            self.parse(tampered, dana_notify_headers(OUR_PATH, raw))
        with self.assertRaises(InvalidCallback):
            self.parse(raw, dana_notify_headers("/somewhere/else/", raw))
        with self.assertRaises(InvalidCallback):
            # Another provider's callback (Rintisan headers): rejected before crypto.
            self.parse(raw, {"x-callback-token": "t", "x-signature": "abc"})
        bad_key = dana_notify_headers(OUR_PATH, raw)
        bad_key["X-SIGNATURE"] = signing.sign("POST", OUR_PATH, raw, bad_key["X-TIMESTAMP"], key_pair("merchant")[0])
        with self.assertRaises(InvalidCallback):
            self.parse(raw, bad_key)

    def test_reply_is_dana_acknowledgement(self):
        body, headers = self.provider.callback_reply("payment")
        self.assertEqual(body, {"responseCode": "2005600", "responseMessage": "Successful"})
        self.assertRegex(headers["X-TIMESTAMP"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+07:00$")
        self.assertEqual(self.provider.callback_reply("disbursement")[0]["responseCode"], "2004300")


class CancelOrderTests(unittest.TestCase):
    def cancel(self, body):
        provider, session = make_dana_provider(FakeResponse(body=body))
        return provider, session

    def test_cancel_success(self):
        provider, session = self.cancel({
            "responseCode": "2005700",
            "responseMessage": "Successful",
            "originalPartnerReferenceNo": "PAY-1",
            "originalReferenceNo": "DANA-1",
            "cancelTime": "2026-11-16T17:07:25+07:00",
        })
        self.assertTrue(provider.supports_cancel_billing)
        result = provider.cancel_billing("PAY-1", provider_trx_id="DANA-1", reason="Dibatalkan orang tua")
        self.assertEqual((result.reference_no, result.provider_trx_id), ("PAY-1", "DANA-1"))
        self.assertEqual(result.cancelled_at, datetime.datetime(2026, 11, 16, 17, 7, 25, tzinfo=WIB))
        self.assertTrue(session.calls[0]["url"].endswith(constants.PATH_CANCEL_ORDER))
        self.assertEqual(
            session.last_json(),
            {
                "originalPartnerReferenceNo": "PAY-1",
                "merchantId": "216620000000000000000",
                "originalReferenceNo": "DANA-1",
                "reason": "Dibatalkan orang tua",
            },
        )

    def test_paid_or_expired_order_is_not_cancellable(self):
        for code in ("4035700", "4045700"):
            with self.subTest(code=code):
                provider, _ = self.cancel({"responseCode": code, "responseMessage": "no"})
                with self.assertRaises(BillingNotCancellable):
                    provider.cancel_billing("PAY-1")

    def test_not_found_and_pending(self):
        provider, _ = self.cancel({"responseCode": "4045701", "responseMessage": "Transaction Not Found"})
        with self.assertRaises(BillingNotFound):
            provider.cancel_billing("PAY-1")
        for code in ("2025700", "4295700", "5005701"):
            with self.subTest(code=code):
                provider, _ = self.cancel({"responseCode": code, "responseMessage": "later"})
                with self.assertRaises(ProviderUnavailable):
                    provider.cancel_billing("PAY-1")


class RefundOrderTests(unittest.TestCase):
    def request(self, **overrides):
        values = dict(reference_no="PAY-1", refund_no="RF-PAY-1-1", amount=Decimal("130000"), provider_trx_id="DANA-1")
        values.update(overrides)
        return RefundRequest(**values)

    def test_refund_success(self):
        provider, session = make_dana_provider(FakeResponse(body={
            "responseCode": "2005800",
            "responseMessage": "Successful",
            "originalPartnerReferenceNo": "PAY-1",
            "refundNo": "REF993883",
            "partnerRefundNo": "RF-PAY-1-1",
            "refundAmount": {"value": "130000.00", "currency": "IDR"},
            "refundTime": "2026-11-16T17:21:41+07:00",
        }))
        self.assertTrue(provider.supports_refund)
        result = provider.refund_billing(self.request(reason="Sudah dibayar tunai"))
        self.assertEqual(result.status, RefundStatus.SUCCESS)
        self.assertEqual((result.refund_no, result.provider_refund_id), ("RF-PAY-1-1", "REF993883"))
        self.assertEqual(result.amount, Decimal("130000.00"))
        self.assertTrue(session.calls[0]["url"].endswith(constants.PATH_REFUND_ORDER))
        sent = session.last_json()
        self.assertEqual(sent["partnerRefundNo"], "RF-PAY-1-1")
        self.assertEqual(sent["refundAmount"], {"value": "130000.00", "currency": "IDR"})
        self.assertEqual(sent["originalReferenceNo"], "DANA-1")
        self.assertEqual(
            (sent["sourcePlatform"], sent["orderTerminalType"], sent["terminalType"]), ("IPG", "SYSTEM", "SYSTEM")
        )
        self.assertEqual(
            sent["additionalInfo"]["actorContext"], {"actorId": "216620000000000000000", "actorType": "MERCHANT"}
        )

    def test_rejected_and_unknown_outcomes(self):
        provider, _ = make_dana_provider(FakeResponse(body={"responseCode": "4045800", "responseMessage": "status"}))
        with self.assertRaises(RefundRejected):
            provider.refund_billing(self.request())
        # In progress, rate limited, internal error, or same refund number with
        # other content: outcome unknown, never "rejected".
        for code in ("2025800", "4295800", "5005801", "4045818"):
            with self.subTest(code=code):
                provider, _ = make_dana_provider(FakeResponse(body={"responseCode": code, "responseMessage": "?"}))
                with self.assertRaises(ProviderUnavailable):
                    provider.refund_billing(self.request())

    def test_refund_needs_whole_rupiah(self):
        provider, session = make_dana_provider()
        with self.assertRaises(InvalidAmount):
            provider.refund_billing(self.request(amount=Decimal("100.50")))
        self.assertEqual(session.calls, [])


class NotYetSupportedTests(unittest.TestCase):
    def test_payouts_and_balance_are_not_configured(self):
        provider, _ = make_dana_provider()
        for call in (
            lambda: provider.transfer_balance(None),
            lambda: provider.get_transfer_status("x"),
            lambda: provider.parse_transfer_callback(b"{}", {}),
            provider.get_balance,
            provider.get_withdrawal_rules,
        ):
            with self.assertRaises(ProviderNotConfigured):
                call()
        self.assertEqual(provider.get_banks(), {})

    def test_withdrawals_stay_off_with_a_fee_until_payout_exists(self):
        provider, _ = make_dana_provider(disbursement_fee=Decimal("2500"))
        with self.assertRaises(ProviderNotConfigured):
            provider.get_withdrawal_rules()

    def test_unknown_channel_fee_is_rejected(self):
        with self.assertRaises(ProviderNotConfigured):
            make_dana_provider(channel_fees={"VIRTUAL_ACCOUNT_XYZ": Decimal("1")})

    def test_channels_offer_only_priced_options(self):
        provider, _ = make_dana_provider(channel_fees=FEES)
        priced = {c.code for c in provider.get_channels() if c.fee is not None}
        self.assertEqual(priced, set(FEES))


if __name__ == "__main__":
    unittest.main()
