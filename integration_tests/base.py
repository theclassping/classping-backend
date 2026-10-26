"""Shared setup for end-to-end API flows that cross several apps.

Every step goes through the public HTTP API with real JWT logins, so these
tests exercise authentication, role module permissions and branch scoping
together. Only the Location reference data is created directly.
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.locations.models import Location
from apps.users.models import User

ADMIN_EMAIL = "admin@classping.test"
GUARDIAN_EMAIL = "guardian@example.com"
PASSWORD = "StrongPassword123!"
FEE_AMOUNT = "250000.00"


class IntegrationTestCase(TestCase):
    def setUp(self):
        # Welcome emails carry the temporary password of accounts created by
        # the API; payment status emails go to the primary guardian.
        welcome_patcher = patch("apps.users.signals.Mailer")
        payment_patcher = patch("apps.payments.serializers.Mailer")
        self.welcome_mailer = welcome_patcher.start()
        self.payment_mailer = payment_patcher.start()
        self.addCleanup(welcome_patcher.stop)
        self.addCleanup(payment_patcher.stop)

        self.location = Location.objects.create(
            name="Jakarta",
            code="JKT",
            location_type="CITY",
        )
        User.objects.create_user(
            email=ADMIN_EMAIL,
            password=PASSWORD,
            first_name="Platform",
            last_name="Admin",
            role=User.Role.ADMIN,
        )

    # ------------------------------------------------------------------
    # Requests
    # ------------------------------------------------------------------

    def login(self, email, password=PASSWORD):
        response = APIClient().post(
            "/api/auth/login/",
            {"email": email, "password": password},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        return client, response.data

    def assert_status(self, response, expected):
        self.assertEqual(response.status_code, expected, getattr(response, "data", None))

    def post(self, client, url, payload, expected=201):
        response = client.post(url, payload, format="json")
        self.assert_status(response, expected)
        return response.data

    def create_account_via_api(self, client, url, payload):
        """POST a record that creates a login and return (data, temporary password)."""
        with self.captureOnCommitCallbacks(execute=True):
            response = client.post(url, payload, format="json")
        self.assert_status(response, 201)
        welcome = [
            call.kwargs
            for call in self.welcome_mailer.return_value.send_template.call_args_list
            if call.kwargs["to_email"] == payload["email"]
        ]
        self.assertEqual(len(welcome), 1, "expected one welcome email")
        return response.data, welcome[0]["variables"]["temporary_password"]

    # ------------------------------------------------------------------
    # School setup
    # ------------------------------------------------------------------

    def create_branch(self, admin, school_id, name, code):
        return self.post(admin, "/api/branches/", {
            "school": school_id,
            "name": name,
            "code": code,
            "address": f"Jl. {name} 1",
            "location_id": self.location.id,
        })["id"]

    def create_staff(self, client, branch_id, email, staff_type="officer", first_name="Siti"):
        """Create a staff profile and return (staff data, logged-in client)."""
        staff, password = self.create_account_via_api(client, "/api/staffs/", {
            "branch": branch_id,
            "first_name": first_name,
            "last_name": staff_type.title(),
            "email": email,
            "staff_type": staff_type,
            "hire_date": str(timezone.localdate()),
            "qualification": "S.Pd" if staff_type == "teacher" else "Administration",
        })
        staff_client, _ = self.login(email, password)
        return staff, staff_client

    def create_class(self, staff_client, branch_id, academic_year_id, name, teacher_id):
        data = self.post(staff_client, "/api/classes/", {
            "name": name,
            "branch": branch_id,
            "academic_year": academic_year_id,
            "teacher_ids": [teacher_id],
        })
        return data["id"], data["class_teachers"][0]["id"]

    def create_new_school(self, slug="pelita", guardian_email=GUARDIAN_EMAIL):
        """Onboard a school through the API and return its records.

        Admin registers the school, its branch and the branch officer; the
        officer then sets up the academic year, a teacher, a class and a
        student with a guardian login.
        """
        today = timezone.localdate()
        admin, _ = self.login(ADMIN_EMAIL)

        school_id = self.post(admin, "/api/schools/", {
            "name": f"Sekolah {slug.title()}",
            "register_number": f"{slug.upper()}-0001",
        })["id"]
        branch_id = self.create_branch(admin, school_id, f"{slug.title()} Kemang", "KMG")

        staff, staff_client = self.create_staff(admin, branch_id, f"officer@{slug}.test")
        self.assertEqual(User.objects.get(pk=staff["user"]).role, User.Role.STAFF)

        academic_year_id = self.post(staff_client, "/api/academic-years/", {
            "name": f"{today.year}/{today.year + 1}",
            "branch": branch_id,
            "start_date": str(today),
            "end_date": str(today + timedelta(days=365)),
            "is_current": True,
        })["id"]

        teacher, teacher_client = self.create_staff(
            staff_client, branch_id, f"teacher@{slug}.test", "teacher", "Budi",
        )
        self.assertEqual(User.objects.get(pk=teacher["user"]).role, User.Role.TEACHER)

        class_id, class_teacher_id = self.create_class(
            staff_client, branch_id, academic_year_id, "Grade 1A", teacher["id"],
        )
        student = self.create_student(staff_client, class_id, "Ayu", "Lestari", guardian_email)

        return {
            "admin": admin,
            "school_id": school_id,
            "branch_id": branch_id,
            "staff_id": staff["id"],
            "staff_client": staff_client,
            "academic_year_id": academic_year_id,
            "teacher_id": teacher["id"],
            "teacher_client": teacher_client,
            "class_id": class_id,
            "class_teacher_id": class_teacher_id,
            "student": student,
        }

    def create_student(self, client, class_id, first_name, last_name, guardian_email):
        """Enroll a student in a class together with a new primary guardian login."""
        return self.post(client, "/api/students/", {
            "first_name": first_name,
            "last_name": last_name,
            "date_of_birth": "2019-03-14",
            "gender": "female",
            "enroll_date": str(timezone.localdate()),
            "status": "active",
            "class_students": [{"class_id": class_id}],
            "student_guardians": [
                {
                    "user": {
                        "email": guardian_email,
                        "password": PASSWORD,
                        "first_name": "Parent of",
                        "last_name": first_name,
                        "phone_number": "081234567890",
                    },
                    "relationship": "mother",
                    "is_primary": True,
                }
            ],
        })

    # ------------------------------------------------------------------
    # Billing
    # ------------------------------------------------------------------

    def bill_class(self, staff_client, branch_id, class_id, name="Field Trip"):
        """Add a one-off fee for a class, generate its invoices, return (fee type, count)."""
        today = timezone.localdate()
        fee_type = self.post(staff_client, "/api/fee-types/", {
            "branch": branch_id,
            "name": name,
            "description": f"{name} fee",
            "amount": FEE_AMOUNT,
            "currency": "IDR",
            "is_recurring": False,
            "class_ids": [class_id],
        })
        generated = self.post(
            staff_client,
            f"/api/fee-types/{fee_type['id']}/generate-invoices/",
            {"invoice_date": str(today), "due_date": str(today + timedelta(days=14))},
            expected=200,
        )
        return fee_type, generated["created_count"]

    def proof(self, key):
        return {
            "image_data": {
                "id": key,
                "object_key": key,
                "storage": "local",
                "filename": key.rsplit("/", 1)[-1],
                "content_type": "image/jpeg",
            },
        }

    def pay_invoice(self, guardian_client, invoice_id, proof_key="payment-proofs/transfer.jpg"):
        return self.post(guardian_client, "/api/payments/", {
            "student_invoice_id": invoice_id,
            "amount": FEE_AMOUNT,
            "payment_method": "bank_transfer",
            "proofs": [self.proof(proof_key)],
        })

    def payment_email_statuses(self):
        return [
            call.kwargs["variables"]["status"]
            for call in self.payment_mailer.return_value.send_template.call_args_list
        ]
