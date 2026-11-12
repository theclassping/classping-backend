"""
Print a signed DANA request as curl, WITHOUT sending it, to paste into DANA's
API Validator (https://dashboard.dana.id/api-validator/ -> "Paste curl").

    python manage.py dana_curl                      # Create Order, BCA VA
    python manage.py dana_curl --channel NETWORK_PAY_PG_CARD --amount 103219
    python manage.py dana_curl --query <DANA referenceNo>

Uses the DANA_* env credentials. The partnerReferenceNo is a fresh TEST-...
value, so pasting it into the validator and pressing Send creates a sandbox
order only.
"""

import datetime
import shlex
import uuid
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone
from payment_aggregator.base import BillingRequest
from payment_aggregator.providers.dana import constants, mapper

from apps.payment_aggregator.aggregator import build_provider


class Command(BaseCommand):
    help = "Print a signed DANA request as curl (not sent) for DANA's API Validator."

    def add_arguments(self, parser):
        parser.add_argument("--channel", default="VIRTUAL_ACCOUNT_BCA")
        parser.add_argument("--amount", default="102775", help="Whole rupiah, fee included.")
        parser.add_argument("--phone", default="6281234567890")
        parser.add_argument("--query", metavar="REFERENCE_NO", help="Print a Query Payment instead.")

    def handle(self, *args, **options):
        provider = build_provider("dana")
        if options["query"]:
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
