"""Ledger / wallet API (Step 7): balance_after, list vs detail, shared list
filters (QueryParamFilter, search, ordering) and opt-in pagination."""

import datetime
from decimal import Decimal

from django.db import transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.payment_gateway.models import GatewayPayment
from apps.payment_gateway.tests import GatewayFixtureMixin

from . import services
from .models import LedgerEntry, Withdrawal
from .serializers import LEDGER_FIELDS

LEDGER_URL = "/api/wallet/ledger/"


class LedgerFixtureMixin(GatewayFixtureMixin):
    """Credit 125.000 (pending), adjustment +50.000, withdrawal 20.000."""

    def setUp(self):
        super().setUp()
        self.staff = APIClient()
        self.staff.force_authenticate(user=self.staff_user)
        self.checkout = self.make_payment(status=GatewayPayment.Status.PAID)
        self.add_item(self.checkout, self.invoice)
        with transaction.atomic():
            services.post_payment_credit(self.checkout)
        services.adjust_balance(None, self.branch.pk, Decimal("50000"), "Opening balance")
        self.withdrawal = Withdrawal.objects.create(
            withdrawal_no="WDR-T-1", branch=self.branch, bank_code="BCA", account_number="5271234567",
            account_holder_name="YAYASAN", amount=Decimal("20000"), fee=Decimal("2500"),
            transfer_amount=Decimal("17500"), provider="rintisan", fee_acknowledged_at=timezone.now(),
        )
        with transaction.atomic():
            services._post_withdrawal_debit(services.lock_wallet(self.branch.pk), self.withdrawal)

    def ledger(self, query=""):
        return self.staff.get(LEDGER_URL + query)


class LedgerApiTests(LedgerFixtureMixin, TestCase):
    def test_list_has_ledger_columns_and_running_total(self):
        response = self.ledger()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data[0]), set(LEDGER_FIELDS))
        self.assertEqual(
            [(row["entry_type"], row["amount"], row["balance_after"]) for row in response.data],
            [
                ("withdrawal_fee", "-2500.00", "155000.00"),
                ("withdrawal", "-17500.00", "157500.00"),
                ("adjustment", "50000.00", "175000.00"),
                ("payment_credit", "125000.00", "125000.00"),
            ],
        )
        wallet = services.lock_wallet(self.branch.pk)
        self.assertEqual(wallet.available_balance + wallet.pending_balance, Decimal("155000"))

    def test_detail_nests_gateway_payment_or_withdrawal(self):
        credit = LedgerEntry.objects.get(entry_type=LedgerEntry.EntryType.PAYMENT_CREDIT)
        detail = self.ledger("{}/".format(credit.pk)).data
        self.assertIsNone(detail["withdrawal"])
        self.assertEqual(detail["gateway_payment"]["payment_no"], "PAY-1")
        self.assertEqual(detail["gateway_payment"]["student_name"], "Budi Santoso")
        self.assertEqual(detail["gateway_payment"]["items"][0]["invoice_no"], "INV-GW-001")

        debit = LedgerEntry.objects.get(entry_type=LedgerEntry.EntryType.WITHDRAWAL)
        detail = self.ledger("{}/".format(debit.pk)).data
        self.assertIsNone(detail["gateway_payment"])
        self.assertEqual(detail["withdrawal"]["withdrawal_no"], "WDR-T-1")
        self.assertEqual(detail["withdrawal"]["transfer_amount"], "17500.00")

    def test_other_branch_cannot_open_an_entry(self):
        other = APIClient()
        other.force_authenticate(user=self.other_branch_staff)
        entry = LedgerEntry.objects.first()
        self.assertEqual(other.get("{}{}/".format(LEDGER_URL, entry.pk)).status_code, 404)
        self.assertEqual(other.get(LEDGER_URL).data, [])

    def test_wallet_summary_counts(self):
        summary = self.staff.get("/api/wallet/").data
        self.assertEqual(summary["pending_count"], 1)
        self.assertEqual((summary["withdrawn_total"], summary["withdrawn_count"]), ("0.00", 0))
        Withdrawal.objects.filter(pk=self.withdrawal.pk).update(status=Withdrawal.Status.SUCCESS)
        summary = self.staff.get("/api/wallet/").data
        self.assertEqual((summary["withdrawn_total"], summary["withdrawn_count"]), ("20000.00", 1))


class ListFilterTests(LedgerFixtureMixin, TestCase):
    """The shared list backends, exercised through the ledger API."""

    def count(self, query):
        response = self.ledger(query)
        self.assertEqual(response.status_code, 200, response.data)
        return len(response.data)

    def test_exact_and_any_of_filters(self):
        self.assertEqual(self.count("?entry_type=adjustment"), 1)
        self.assertEqual(self.count("?entry_type=withdrawal,withdrawal_fee"), 2)
        self.assertEqual(self.count("?settlement_status=pending_settlement"), 1)
        self.assertEqual(self.count("?entry_type="), 4)  # empty value is ignored
        self.assertEqual(self.count("?unknown=1"), 4)  # undeclared params are ignored

    def test_invalid_values_are_400(self):
        for query, param in (("?entry_type=bogus", "entry_type"), ("?date_from=yesterday", "date_from")):
            response = self.ledger(query)
            self.assertEqual(response.status_code, 400, query)
            self.assertEqual((response.data["code"], response.data["param"]), ("INVALID_FILTER", param))

    def test_date_range(self):
        today = timezone.localdate()
        tomorrow = today + datetime.timedelta(days=1)
        self.assertEqual(self.count("?date_from={}&date_to={}".format(today, today)), 4)
        self.assertEqual(self.count("?date_from={}".format(tomorrow)), 0)

    def test_search_reaches_related_rows(self):
        self.assertEqual(self.count("?search=Budi"), 1)  # student of the checkout
        self.assertEqual(self.count("?search=INV-GW-001"), 1)  # invoice in the checkout
        self.assertEqual(self.count("?search=WDR-T-1"), 2)  # note of both withdrawal entries

    def test_ordering(self):
        amounts = [row["amount"] for row in self.ledger("?ordering=amount").data]
        self.assertEqual(amounts[0], "-17500.00")
        self.assertEqual(amounts[-1], "125000.00")

    def test_pagination_only_with_page_param(self):
        response = self.ledger()
        self.assertEqual(len(response.data), 4)
        self.assertEqual((response["X-Total-Count"], response["X-Total-Pages"]), ("4", "1"))

        response = self.ledger("?page=2&page_size=3")
        self.assertEqual(len(response.data), 1)
        self.assertEqual(
            (response["X-Total-Count"], response["X-Page"], response["X-Page-Size"], response["X-Total-Pages"]),
            ("4", "2", "3", "2"),
        )


class GatewayPaymentListFilterTests(GatewayFixtureMixin, TestCase):
    """gateway/payments uses the same declared filters."""

    def setUp(self):
        super().setUp()
        self.staff = APIClient()
        self.staff.force_authenticate(user=self.staff_user)
        self.make_payment("PAY-1", "k1", status=GatewayPayment.Status.PAID, needs_refund=True)
        self.make_payment("PAY-2", "k2", status=GatewayPayment.Status.EXPIRED)

    def payment_nos(self, query):
        response = self.staff.get("/api/gateway/payments/" + query)
        self.assertEqual(response.status_code, 200, response.data)
        return sorted(row["payment_no"] for row in response.data)

    def test_filters(self):
        self.assertEqual(self.payment_nos("?status=paid,expired"), ["PAY-1", "PAY-2"])
        self.assertEqual(self.payment_nos("?needs_refund=true"), ["PAY-1"])
        self.assertEqual(self.payment_nos("?needs_refund=false"), ["PAY-2"])
        self.assertEqual(self.payment_nos("?student_id={}".format(self.student.pk)), ["PAY-1", "PAY-2"])
        self.assertEqual(self.payment_nos("?search=PAY-2"), ["PAY-2"])
        response = self.staff.get("/api/gateway/payments/?student_id=abc")
        self.assertEqual((response.status_code, response.data["code"]), (400, "INVALID_FILTER"))
