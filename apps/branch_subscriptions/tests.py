from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.branch_subscriptions.errors import StudentLimitReached, SubscriptionFeatureLocked
from apps.branch_subscriptions.models import SubscriptionPayment
from apps.branch_subscriptions import payments
from apps.locations.models import Location
from apps.schools.models import Branch, School
from apps.staffs.models import Staff
from apps.students.models import Student
from apps.uploads.services.media import StorageFullError, StorageLockedError
from apps.uploads.usage import ensure_capacity
from apps.users.models import User
from apps.wallets.models import BranchWallet
from payment_aggregator.base import BillingResult, BillingStatus, FeeBreakdown
from plan_subscriptions import entitlements, services
from plan_subscriptions.models import (
    AddOn,
    Feature,
    FeatureOverride,
    Plan,
    Subscription,
    SubscriptionEvent,
    SubscriptionInvoice,
)

GB = 1024 ** 3
DAY = timedelta(days=1)


def make_branch(code="B1"):
    location = Location.objects.create(name=f"Loc {code}", code=f"L{code}", location_type="COUNTRY")
    school = School.objects.create(name=f"School {code}", register_number=f"REG-{code}")
    return Branch.objects.create(school=school, location=location, name=f"Branch {code}", code=code,
                                 email=f"{code.lower()}@branch.test", phone="0221234567")


def make_student(branch, status="active", name="Kid"):
    return Student.objects.create(first_name=name, last_name="X", date_of_birth=date(2019, 1, 1), gender="male",
                                  enroll_date=date(2026, 1, 1), status=status, branch=branch)


def make_staff(branch, email="officer@branch.test", staff_type=Staff.StaffType.OFFICER):
    user = User.objects.create_user(email=email, password="StrongPassword123!", role=User.Role.STAFF)
    Staff.objects.create(user=user, branch=branch, first_name="Ofi", last_name="Cer", email=email, phone="0812345678",
                         staff_type=staff_type, hire_date=date(2026, 1, 1), qualification="S1")
    return user


def price(code):
    return Plan.objects.get(code=code).current_price()


class TrialTests(TestCase):
    def test_new_branch_starts_trial_on_starter(self):
        branch = make_branch()
        sub = Subscription.objects.get(subscriber=branch)
        self.assertEqual(sub.status, "trialing")
        self.assertEqual(sub.plan.code, "starter")
        self.assertAlmostEqual((sub.trial_end - sub.trial_start).days, 180)
        self.assertEqual(entitlements.limit(branch, "max_students"), 100)
        self.assertEqual(entitlements.limit(branch, "storage_bytes"), 50 * GB)
        self.assertTrue(entitlements.has(branch, "payment_gateway"))

    def test_read_only_starts_exactly_at_grace_end_without_the_job(self):
        branch = make_branch()
        sub = branch.plan_subscription
        end = sub.trial_end
        self.assertEqual(entitlements.state(branch, "storage_bytes", now=end - DAY), "active")
        # Past due: features stay on for GRACE_DAYS.
        self.assertEqual(entitlements.resolve(branch, end + 6 * DAY)["status"], "past_due")
        self.assertEqual(entitlements.state(branch, "storage_bytes", now=end + 6 * DAY), "active")
        # One second after the grace period: read-only, though the stored status was never changed.
        moment = end + 7 * DAY + timedelta(seconds=1)
        self.assertEqual(Subscription.objects.get(pk=sub.pk).status, "trialing")
        self.assertEqual(entitlements.state(branch, "storage_bytes", now=moment), "read_only")
        self.assertEqual(entitlements.state(branch, "max_students", now=moment), "read_only")
        self.assertFalse(entitlements.has(branch, "payment_gateway", now=moment))

    def test_job_writes_status_and_emails_once(self):
        branch = make_branch()
        sub = branch.plan_subscription
        with mock.patch("plan_subscriptions.notify.send", return_value=True) as send, \
                self.captureOnCommitCallbacks(execute=True):
            services.advance_statuses(now=sub.trial_end + DAY)
            services.advance_statuses(now=sub.trial_end + 2 * DAY)
            self.assertEqual(Subscription.objects.get(pk=sub.pk).status, "past_due")
            services.advance_statuses(now=sub.trial_end + 8 * DAY)
        sub.refresh_from_db()
        self.assertEqual(sub.status, "expired")
        events = [call.args[0] for call in send.call_args_list]
        self.assertEqual(events.count("payment_overdue"), 1)
        self.assertEqual(events.count("expired"), 1)


class SubscribeTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.sub = self.branch.plan_subscription

    def test_pick_growth_after_trial_keeps_starter_limits_until_trial_ends(self):
        invoice = services.subscribe(self.sub, price("growth"))
        self.assertEqual(invoice.period_start, self.sub.trial_end)
        self.assertEqual(invoice.subtotal, Decimal("449000"))
        self.assertEqual(invoice.tax, Decimal("49390"))
        services.mark_invoice_paid(invoice, paid_ref="SUB-1")
        self.assertEqual(entitlements.limit(self.branch, "max_students"), 100)
        after = self.sub.trial_end + DAY
        self.assertEqual(entitlements.limit(self.branch, "max_students", now=after), 300)
        services.advance_statuses(now=after)
        self.sub.refresh_from_db()
        self.assertEqual((self.sub.status, self.sub.plan.code), ("active", "growth"))

    def test_start_now_with_pro_ends_trial_and_applies_pro_immediately(self):
        invoice = services.subscribe(self.sub, price("pro"), start="now")
        services.mark_invoice_paid(invoice, paid_ref="SUB-2")
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, "active")
        self.assertEqual(self.sub.plan.code, "pro")
        self.assertLessEqual(self.sub.trial_end, timezone.now())
        self.assertEqual(entitlements.limit(self.branch, "max_students"), 500)

    def test_start_now_on_the_trial_plan_is_refused(self):
        with self.assertRaises(Exception):
            services.subscribe(self.sub, price("starter"), start="now")

    def test_renewal_invoice_issued_before_trial_end_with_addons(self):
        services.issue_due_invoices(now=self.sub.trial_end - 6 * DAY)
        invoice = self.sub.invoices.get(kind="first")
        self.assertEqual(invoice.subtotal, Decimal("199000"))
        services.issue_due_invoices(now=self.sub.trial_end - 5 * DAY)
        self.assertEqual(self.sub.invoices.filter(kind="first").count(), 1)


class AddonTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        sub = self.branch.plan_subscription
        invoice = services.subscribe(sub, price("starter"), start="period")
        services.mark_invoice_paid(invoice, paid_ref="x")
        self.now = sub.trial_end + 10 * DAY
        services.advance_statuses(now=sub.trial_end + DAY)
        self.sub = Subscription.objects.get(pk=sub.pk)
        self.addon = AddOn.objects.get(code="storage_10gb")

    def test_storage_addon_is_prorated_and_adds_up_once_paid(self):
        purchase, invoice = services.buy_addon(self.sub, self.addon, 1, now=self.now)
        self.assertEqual(purchase.status, "pending_payment")
        self.assertLess(invoice.subtotal, Decimal("50000"))
        self.assertGreater(invoice.subtotal, Decimal("0"))
        self.assertEqual(entitlements.limit(self.branch, "storage_bytes", now=self.now), 50 * GB)
        services.mark_invoice_paid(invoice, paid_at=self.now)
        second, invoice2 = services.buy_addon(self.sub, self.addon, 2, now=self.now)
        services.mark_invoice_paid(invoice2, paid_at=self.now)
        self.assertEqual(entitlements.limit(self.branch, "storage_bytes", now=self.now + DAY), 80 * GB)

    def test_max_quantity(self):
        with self.assertRaises(Exception) as ctx:
            services.buy_addon(self.sub, self.addon, 11, now=self.now)
        self.assertEqual(ctx.exception.code, "ADDON_QUANTITY_EXCEEDED")

    def test_unpaid_addon_invoice_is_voided(self):
        purchase, invoice = services.buy_addon(self.sub, self.addon, 1, now=self.now)
        services.advance_statuses(now=self.now + 8 * DAY)
        invoice.refresh_from_db()
        purchase.refresh_from_db()
        self.assertEqual((invoice.status, purchase.status), ("void", "void"))


class StudentLimitTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        FeatureOverride.objects.create(subscriber=self.branch, feature=Feature.objects.get(code="max_students"), value=2)
        entitlements.invalidate(self.branch)

    def test_blocks_the_student_over_the_limit(self):
        make_student(self.branch, name="A")
        make_student(self.branch, name="B")
        with self.assertRaises(StudentLimitReached):
            make_student(self.branch, name="C")
        make_student(self.branch, status="graduated", name="D")  # not active: allowed

    def test_reactivating_counts(self):
        make_student(self.branch, name="A")
        make_student(self.branch, name="B")
        old = make_student(self.branch, status="inactive", name="C")
        old.status = "active"
        with self.assertRaises(StudentLimitReached):
            old.save()

    def test_students_in_a_class_of_the_branch_count_too(self):
        from apps.academic_years.models import AcademicYear
        from apps.classes.models import Class, ClassStudent

        year = AcademicYear.objects.create(branch=self.branch, name="2026", start_date=date(2026, 1, 1),
                                           end_date=date(2026, 12, 31))
        class_obj = Class.objects.create(branch=self.branch, academic_year=year, name="1A")
        for name in ("A", "B"):
            student = make_student(None, name=name)  # no Student.branch: belongs through the class
            ClassStudent.objects.create(student=student, class_obj=class_obj, is_current=True)
        self.assertEqual(entitlements.raw_limit(self.branch, "max_students"), 2)
        third = make_student(None, name="C")
        with self.assertRaises(StudentLimitReached):
            ClassStudent.objects.create(student=third, class_obj=class_obj, is_current=True)
        # Re-saving an enrollment the student already counts with takes no new seat.
        assignment = ClassStudent.objects.get(student__first_name="A")
        assignment.is_current = True
        assignment.save()

    def test_expired_branch_cannot_add_students(self):
        Subscription.objects.filter(subscriber=self.branch).update(status="expired")
        entitlements.invalidate(self.branch)
        with self.assertRaises(SubscriptionFeatureLocked):
            make_student(self.branch)

    def test_api_returns_student_limit_reached(self):
        make_student(self.branch, name="A")
        make_student(self.branch, name="B")
        error = None
        try:
            make_student(self.branch, name="C")
        except StudentLimitReached as exc:
            error = exc
        self.assertEqual(error.detail["code"], "STUDENT_LIMIT_REACHED")
        self.assertEqual(error.detail["limit"], 2)


class StorageAndGatewayTests(TestCase):
    def setUp(self):
        self.branch = make_branch()

    def test_storage_limit_and_read_only(self):
        FeatureOverride.objects.create(subscriber=self.branch, feature=Feature.objects.get(code="storage_bytes"), value=100)
        entitlements.invalidate(self.branch)
        ensure_capacity(self.branch.pk, 100)
        with self.assertRaises(StorageFullError):
            ensure_capacity(self.branch.pk, 101)
        Subscription.objects.filter(subscriber=self.branch).update(status="expired")
        entitlements.invalidate(self.branch)
        with self.assertRaises(StorageLockedError):
            ensure_capacity(self.branch.pk, 1)

    def test_legacy_capacity_field_becomes_an_override(self):
        self.branch.storage_capacity_bytes = 7 * GB
        self.branch.save()
        self.assertEqual(entitlements.limit(self.branch, "storage_bytes"), 7 * GB)
        self.branch.storage_capacity_bytes = None
        self.branch.save()
        self.assertEqual(entitlements.limit(self.branch, "storage_bytes"), 50 * GB)

    def test_gateway_off_after_expiry(self):
        self.assertTrue(entitlements.has(self.branch, "payment_gateway"))
        Subscription.objects.filter(subscriber=self.branch).update(status="expired")
        entitlements.invalidate(self.branch)
        self.assertFalse(entitlements.has(self.branch, "payment_gateway"))


def fake_fee(channel_code, total):
    fee = Decimal("4440")
    return FeeBreakdown(channel_code, "BCA Virtual Account", "virtual_account", total, fee, total + fee)


class OnlinePaymentTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.user = make_staff(self.branch, staff_type=Staff.StaffType.TEACHER)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        patcher = mock.patch("apps.branch_subscriptions.payments.PaymentAggregator")
        self.aggregator = patcher.start()
        self.addCleanup(patcher.stop)
        self.aggregator.calculate_transaction_fee.side_effect = fake_fee
        self.aggregator.provider_name.return_value = "dana"
        self.aggregator.get_channels.side_effect = lambda total: [fake_fee("VA_BCA", total)]
        self.aggregator.using.return_value.create_billing.side_effect = lambda request: BillingResult(
            reference_no=request.reference_no, provider_trx_id="TRX-" + request.reference_no,
            payment_code="88001234", billing_url="https://pay.test/x",
        )

    def test_any_staff_sees_the_subscription(self):
        response = self.client.get("/api/subscription/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "trialing")
        self.assertEqual(response.data["plan"]["code"], "starter")
        self.assertEqual(response.data["features"]["max_students"]["value"], 100)
        self.assertIn("usage", response.data)

    def test_buy_storage_goes_straight_to_payment_and_webhook_activates_it(self):
        wallet_before = BranchWallet.objects.filter(branch=self.branch).count()
        response = self.client.post(
            "/api/subscription/addons/", {"addon_code": "storage_10gb", "quantity": 1, "channel_code": "VA_BCA"},
            format="json", HTTP_IDEMPOTENCY_KEY="buy-1",
        )
        self.assertEqual(response.status_code, 201, response.data)
        payment = response.data["payment"]
        self.assertTrue(payment["payment_no"].startswith("SUB-"))
        self.assertEqual(payment["payment_code"], "88001234")
        self.assertEqual(Decimal(payment["transaction_fee"]), Decimal("4440"))
        self.assertEqual(entitlements.limit(self.branch, "storage_bytes"), 50 * GB)

        # Same Idempotency-Key: same purchase, no second invoice.
        again = self.client.post(
            "/api/subscription/addons/", {"addon_code": "storage_10gb", "quantity": 1, "channel_code": "VA_BCA"},
            format="json", HTTP_IDEMPOTENCY_KEY="buy-1",
        )
        self.assertEqual(again.data["invoice"]["id"], response.data["invoice"]["id"])

        billing = BillingResult(reference_no=payment["payment_no"], provider_trx_id="TRX-" + payment["payment_no"],
                                status=BillingStatus.PAID, amount=Decimal(payment["amount"]))
        with mock.patch("plan_subscriptions.notify.send", return_value=True):
            self.assertEqual(payments.apply_callback("dana", billing), "ok")
        self.assertEqual(SubscriptionPayment.objects.get(payment_no=payment["payment_no"]).status, "paid")
        self.assertEqual(SubscriptionInvoice.objects.get(pk=response.data["invoice"]["id"]).status, "paid")
        entitlements.invalidate(self.branch)
        self.assertEqual(entitlements.limit(self.branch, "storage_bytes"), 60 * GB)
        self.assertEqual(BranchWallet.objects.filter(branch=self.branch).count(), wallet_before)

    def test_payment_webhook_routes_sub_references(self):
        from apps.payment_gateway import services as gateway_services

        invoice = services.subscribe(self.branch.plan_subscription, price("pro"), start="now")
        data = payments.start_payment(invoice, "VA_BCA", self.user)
        billing = BillingResult(reference_no=data["payment_no"], provider_trx_id="T", status=BillingStatus.PAID,
                                amount=Decimal(data["amount"]))
        with mock.patch("plan_subscriptions.notify.send", return_value=True):
            self.assertEqual(gateway_services._apply_payment_callback("dana", billing), "ok")
        self.assertEqual(Subscription.objects.get(subscriber=self.branch).plan.code, "pro")

    def test_parent_cannot_use_the_subscription_api(self):
        parent = User.objects.create_user(email="p@x.test", password="StrongPassword123!", role=User.Role.PARENT)
        client = APIClient()
        client.force_authenticate(parent)
        self.assertEqual(client.get("/api/subscription/").status_code, 403)


class EmailTests(TestCase):
    def test_variables_use_branch_as_school_name_and_go_to_branch_and_staff(self):
        branch = make_branch()
        make_staff(branch, email="a@branch.test")
        sub = branch.plan_subscription
        sent = []

        class FakeMailer:
            def send_template(self, **kwargs):
                sent.append(kwargs)

        with self.settings(MAILJET_API_KEY="k"), mock.patch("apps.branch_subscriptions.notify.Mailer", FakeMailer):
            from apps.branch_subscriptions.notify import MailjetNotifier

            MailjetNotifier().send("expired", sub, {"plan": sub.plan, "expired_at": timezone.now()})
        self.assertEqual({m["to_email"] for m in sent}, {"b1@branch.test", "a@branch.test"})
        self.assertEqual(sent[0]["template_id"], 8542045)
        self.assertEqual(sent[0]["variables"]["school_name"], "School B1 – Branch B1")
        self.assertIn("expired_date", sent[0]["variables"])


class AdminWebTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email="root@x.test", password="StrongPassword123!", role="ADMIN")
        self.client.force_login(self.admin)
        self.branch = make_branch()
        self.sub = self.branch.plan_subscription

    def test_pages_load(self):
        for url in ("/admin-web/subscriptions/", f"/admin-web/subscriptions/{self.sub.pk}/", "/admin-web/plans/",
                    "/admin-web/plans/new/", f"/admin-web/plans/{self.sub.plan_id}/", "/admin-web/plans/features/",
                    "/admin-web/plans/features/new/", "/admin-web/plans/addons/", "/admin-web/plans/addons/new/",
                    f"/admin-web/plans/addons/{AddOn.objects.get(code='storage_10gb').pk}/"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)

    def test_new_price_keeps_existing_branches_on_old_price(self):
        plan = Plan.objects.get(code="starter")
        old_price = self.sub.price
        storage = Feature.objects.get(code="storage_bytes")
        students = Feature.objects.get(code="max_students")
        gateway = Feature.objects.get(code="payment_gateway")
        response = self.client.post(f"/admin-web/plans/{plan.pk}/", {
            "name": "Starter", "price": "209000", "sort_order": "1", "is_public": "on", "is_active": "on",
            f"f_{students.pk}_mode": "limit", f"f_{students.pk}": "120",
            f"f_{storage.pk}_mode": "limit", f"f_{storage.pk}": "55",
            f"f_{gateway.pk}_mode": "on",
        })
        self.assertEqual(response.status_code, 302)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.price_id, old_price.pk)
        self.assertEqual(plan.current_price().amount, Decimal("209000"))
        entitlements.invalidate(self.branch)
        self.assertEqual(entitlements.limit(self.branch, "max_students"), 120)
        self.assertEqual(entitlements.limit(self.branch, "storage_bytes"), 55 * GB)

    def test_mark_paid_and_override(self):
        invoice = services.subscribe(self.sub, price("growth"))
        self.client.post(f"/admin-web/subscriptions/{self.sub.pk}/",
                         {"action": "mark_paid", "invoice_id": invoice.pk, "reference": "BCA 123"})
        invoice.refresh_from_db()
        self.assertEqual((invoice.status, invoice.paid_ref), ("paid", "manual: BCA 123"))
        students = Feature.objects.get(code="max_students")
        self.client.post(f"/admin-web/subscriptions/{self.sub.pk}/",
                         {"action": "set_override", "feature_id": students.pk, "value": "650", "reason": "Big school"})
        entitlements.invalidate(self.branch)
        self.assertEqual(entitlements.limit(self.branch, "max_students"), 650)
