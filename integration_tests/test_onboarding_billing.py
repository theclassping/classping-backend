from apps.users.models import User

from .base import FEE_AMOUNT, GUARDIAN_EMAIL, IntegrationTestCase


class SchoolOnboardingTests(IntegrationTestCase):
    def test_create_new_school(self):
        school = self.create_new_school()
        student = school["student"]

        # Staff sees the new student in the class roster.
        roster = school["staff_client"].get(f"/api/classes/{school['class_id']}/students/")
        self.assert_status(roster, 200)
        self.assertEqual([row["student_id"] for row in roster.data], [student["id"]])

        # The teacher sees only their assigned class.
        classes = school["teacher_client"].get("/api/classes/")
        self.assert_status(classes, 200)
        self.assertEqual([row["id"] for row in classes.data], [school["class_id"]])

        # The guardian can log in and is linked to their child.
        _, login = self.login(GUARDIAN_EMAIL)
        self.assertEqual(login["user"]["role"], User.Role.PARENT)
        self.assertEqual(
            [child["student_id"] for child in login["user"]["guardian_students"]],
            [student["id"]],
        )


class BillingFlowTests(IntegrationTestCase):
    def setUp(self):
        super().setUp()
        self.school = self.create_new_school()
        self.staff_client = self.school["staff_client"]
        self.fee_type, created = self.bill_class(
            self.staff_client, self.school["branch_id"], self.school["class_id"],
        )
        self.assertEqual(created, 1)
        self.guardian_client, _ = self.login(GUARDIAN_EMAIL)

    def get_invoice(self, invoice_id):
        response = self.guardian_client.get(f"/api/student-invoices/{invoice_id}/")
        self.assert_status(response, 200)
        return response.data

    def verify(self, payment_id, payload, expected=200):
        response = self.staff_client.patch(f"/api/payments/{payment_id}/", payload, format="json")
        self.assert_status(response, expected)
        return response.data

    def test_fee_invoice_payment_and_verification(self):
        # The guardian sees the new unpaid invoice for their child.
        invoices = self.guardian_client.get("/api/student-invoices/")
        self.assert_status(invoices, 200)
        self.assertEqual(len(invoices.data), 1)
        invoice = invoices.data[0]
        self.assertEqual(invoice["student_id"], self.school["student"]["id"])
        self.assertEqual(invoice["fee_type"]["id"], self.fee_type["id"])
        self.assertEqual(invoice["status"], "unpaid")
        self.assertEqual(invoice["total_amount"], FEE_AMOUNT)
        self.assertIsNone(invoice["payment"])

        # The guardian pays with a transfer proof.
        payment = self.pay_invoice(self.guardian_client, invoice["id"])
        self.assertEqual(payment["status"], "submitted")
        self.assertEqual(len(payment["proofs"]), 1)
        self.assertEqual(self.get_invoice(invoice["id"])["status"], "payment_submitted")

        # A guardian cannot verify their own payment.
        self_verify = self.guardian_client.patch(
            f"/api/payments/{payment['id']}/", {"status": "completed"}, format="json",
        )
        self.assert_status(self_verify, 403)

        # Staff finds the submitted payment and verifies it.
        pending = self.staff_client.get("/api/payments/", {"status": "submitted"})
        self.assert_status(pending, 200)
        self.assertEqual([row["id"] for row in pending.data], [payment["id"]])
        self.verify(payment["id"], {"status": "completed"})

        # The invoice is now paid, as seen by the guardian.
        paid = self.get_invoice(invoice["id"])
        self.assertEqual(paid["status"], "paid")
        self.assertEqual(paid["amount_paid"], FEE_AMOUNT)
        self.assertFalse(paid["is_overdue"])
        self.assertEqual(paid["payment"]["status"], "completed")
        self.assertEqual(paid["payment"]["verified_by_id"], self.school["staff_id"])
        self.assertIsNotNone(paid["payment"]["paid_at"])

        # The primary guardian was emailed on submission and on verification.
        self.assertEqual(self.payment_email_statuses(), ["submitted", "completed"])
        recipients = {
            call.kwargs["to_email"]
            for call in self.payment_mailer.return_value.send_template.call_args_list
        }
        self.assertEqual(recipients, {GUARDIAN_EMAIL})

    def test_rejected_payment_is_reuploaded_and_verified(self):
        invoice_id = self.guardian_client.get("/api/student-invoices/").data[0]["id"]
        payment = self.pay_invoice(self.guardian_client, invoice_id, "payment-proofs/blurry.jpg")

        # Staff rejects the proof with a reason the guardian can act on.
        self.verify(payment["id"], {"status": "rejected", "rejection_reason": "Proof is blurry"})

        rejected = self.get_invoice(invoice_id)
        self.assertEqual(rejected["status"], "unpaid")
        self.assertEqual(rejected["amount_paid"], "0.00")
        self.assertEqual(rejected["payment"]["status"], "rejected")
        self.assertEqual(rejected["payment"]["rejection_reason"], "Proof is blurry")
        self.assertEqual(rejected["payment"]["verified_by_id"], self.school["staff_id"])

        # The invoice already has a payment, so the guardian re-uploads a proof
        # on it rather than paying a second time.
        self.post(self.guardian_client, "/api/payments/", {
            "student_invoice_id": invoice_id,
            "amount": FEE_AMOUNT,
            "payment_method": "bank_transfer",
        }, expected=400)
        self.post(self.guardian_client, "/api/payment-proofs/", {
            "payment_id": payment["id"],
            **self.proof("payment-proofs/clear.jpg"),
        })

        resubmitted = self.get_invoice(invoice_id)
        self.assertEqual(resubmitted["status"], "payment_submitted")
        self.assertEqual(resubmitted["payment"]["status"], "submitted")
        self.assertIsNone(resubmitted["payment"]["rejection_reason"])
        self.assertIsNone(resubmitted["payment"]["verified_by_id"])
        self.assertEqual(
            sorted(proof["image_data"]["id"] for proof in resubmitted["payment"]["proofs"]),
            ["payment-proofs/blurry.jpg", "payment-proofs/clear.jpg"],
        )

        # Staff sees it back in the queue and verifies it this time.
        pending = self.staff_client.get("/api/payments/", {"status": "submitted"})
        self.assertEqual([row["id"] for row in pending.data], [payment["id"]])
        self.verify(payment["id"], {"status": "completed"})

        paid = self.get_invoice(invoice_id)
        self.assertEqual(paid["status"], "paid")
        self.assertEqual(paid["amount_paid"], FEE_AMOUNT)
        self.assertEqual(paid["payment"]["status"], "completed")
        self.assertIsNone(paid["payment"]["rejection_reason"])
        self.assertEqual(self.payment_email_statuses(), ["submitted", "rejected", "completed"])
