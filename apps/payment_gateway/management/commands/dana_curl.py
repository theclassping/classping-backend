"""
Print a signed DANA request as curl, WITHOUT sending it, to paste into DANA's
API Validator (https://dashboard.dana.id/api-validator/ -> "Paste curl").

    python manage.py dana_curl                      # Create Order, BCA VA
    python manage.py dana_curl --channel NETWORK_PAY_PG_CARD --amount 103219
    python manage.py dana_curl --query <DANA referenceNo>
    python manage.py dana_curl --bank-inquiry 2460888509 --bank BCA --amount 50000
    python manage.py dana_curl --bank-inquiry 2460888509 --customer-number 62811742234

    python manage.py dana_curl --transfer-bank 2460888509 --bank BCA --amount 50000
    python manage.py dana_curl --transfer-status WDR-20261116-000001

--bank-inquiry / --transfer-bank build the exact Transfer to Bank Account
Inquiry / Transfer to Bank body a withdrawal sends (same mapper); --amount is
then the amount sent to the bank (after the fee), customerNumber defaults to
DANA_PAYOUT_PHONE and --reference sets partnerReferenceNo (default TEST-...).
Sending a Transfer to Bank moves money out of the disbursement account.

Uses the DANA_* env credentials. The partnerReferenceNo is a fresh TEST-...
value, so pasting it into the validator and pressing Send creates a sandbox
order only.
"""

import dataclasses
import datetime
import shlex
import uuid
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone
from payment_aggregator.base import BillingRequest, TransferRequest
from payment_aggregator.providers.dana import constants, mapper

from apps.payment_aggregator.aggregator import build_provider


class Command(BaseCommand):
    help = "Print a signed DANA request as curl (not sent) for DANA's API Validator."

    def add_arguments(self, parser):
        parser.add_argument("--channel", default="VIRTUAL_ACCOUNT_BCA")
        parser.add_argument("--amount", default="102775", help="Whole rupiah, fee included.")
        parser.add_argument("--phone", default="6281234567890")
        parser.add_argument("--query", metavar="REFERENCE_NO", help="Print a Query Payment instead.")
        parser.add_argument(
            "--bank-inquiry", metavar="ACCOUNT_NUMBER", help="Print a Transfer to Bank Account Inquiry instead."
        )
        parser.add_argument("--transfer-bank", metavar="ACCOUNT_NUMBER", help="Print a Transfer to Bank instead.")
        parser.add_argument(
            "--transfer-status", metavar="REFERENCE_NO", help="Print a Transfer to Bank Inquiry Status instead."
        )
        parser.add_argument("--bank", default="BCA", help="Classping bank code (BCA -> 014). Payouts only.")
        parser.add_argument("--account-name", default="Classping Test", help="Payouts only.")
        parser.add_argument("--customer-number", help="Payouts only; default DANA_PAYOUT_PHONE.")
        parser.add_argument("--reference", help="Payouts only: partnerReferenceNo (default TEST-...).")

    def handle(self, *args, **options):
        provider = build_provider("dana")
        if options["bank_inquiry"]:
            url, headers, body = self._payout(
                provider, options, options["bank_inquiry"], constants.PATH_BANK_ACCOUNT_INQUIRY,
                mapper.bank_inquiry_payload,
            )
        elif options["transfer_bank"]:
            url, headers, body = self._payout(
                provider, options, options["transfer_bank"], constants.PATH_TRANSFER_BANK, mapper.transfer_payload
            )
        elif options["transfer_status"]:
            url, headers, body = provider.client.signed_request(
                constants.PATH_TRANSFER_STATUS, mapper.transfer_status_payload(options["transfer_status"])
            )
        elif options["query"]:
            url, headers, body = provider.client.signed_request(
                constants.PATH_QUERY_PAYMENT, mapper.query_payload(options["query"], provider.config)
            )
        else:
            request = BillingRequest(
                reference_no="TEST-" + uuid.uuid4().hex[:16].upper(),
                channel_code=options["channel"],
                amount=Decimal(options["amount"]),
                invoice_date=timezone.localdate(),
                expires_at=timezone.now() + datetime.timedelta(minutes=30),
                payer_name="Classping Test",
                payer_phone=options["phone"],
                note="Classping validator test",
            )
            url, headers, body = provider.order_request(request)

        lines = ["curl -X POST " + shlex.quote(url)]
        lines += ["  -H " + shlex.quote("{}: {}".format(name, value)) for name, value in headers.items()]
        lines.append("  --data-raw " + shlex.quote(body))
        self.stdout.write(" \\\n".join(lines))

    def _payout(self, provider, options, account_number, path, build_payload):
        """Inquiry / transfer body built by the same mapper as a real withdrawal."""
        config = provider.config
        if options["customer_number"]:
            config = dataclasses.replace(config, payout_phone=options["customer_number"])
        config.require_payout_settings()
        request = TransferRequest(
            reference_no=options["reference"] or "TEST-" + uuid.uuid4().hex[:16].upper(),
            amount=Decimal(options["amount"]),
            bank_code=options["bank"],
            account_number=account_number,
            account_name=options["account_name"],
        )
        payload = build_payload(
            request, config, mapper.dana_bank(request.bank_code), mapper.whole_rupiah(request.amount)
        )
        return provider.client.signed_request(path, payload)
