from django.utils import timezone

from .base import GUARDIAN_EMAIL, IntegrationTestCase


class BranchIsolationTests(IntegrationTestCase):
    """Staff only reach records of their own branch, across schools and within one."""

    def setUp(self):
        super().setUp()
        # Pelita Kemang owns the records under test: a class, student,
        # guardian, invoice, payment and published activity.
        self.pelita = self.create_new_school("pelita")
        staff_client = self.pelita["staff_client"]
        self.fee_type, _ = self.bill_class(
            staff_client, self.pelita["branch_id"], self.pelita["class_id"],
        )
        guardian_client, _ = self.login(GUARDIAN_EMAIL)
        self.invoice_id = guardian_client.get("/api/student-invoices/").data[0]["id"]
        self.payment = self.pay_invoice(guardian_client, self.invoice_id)
        self.activity = self.post(self.pelita["teacher_client"], "/api/activities/", {
            "class_teacher_id": self.pelita["class_teacher_id"],
            "class_id": self.pelita["class_id"],
            "name": "Painting Day",
            "activity_date": str(timezone.localdate()),
            "is_publish": True,
            "student_ids": [self.pelita["student"]["id"]],
        })

        # Another branch of the same school, and a different school.
        depok_id = self.create_branch(self.pelita["admin"], self.pelita["school_id"], "Pelita Depok", "DPK")
        _, depok_staff = self.create_staff(self.pelita["admin"], depok_id, "officer.depok@pelita.test")
        self.harapan = self.create_new_school("harapan", guardian_email="guardian@harapan.test")

        self.outsiders = {
            "same school, other branch staff": (depok_staff, depok_id),
            "other school staff": (self.harapan["staff_client"], self.harapan["branch_id"]),
            "other school teacher": (self.harapan["teacher_client"], self.harapan["branch_id"]),
        }

    def pelita_records(self):
        student = self.pelita["student"]
        guardian_id = student["student_guardians"][0]["guardian_id"]
        return {
            "/api/branches/": self.pelita["branch_id"],
            "/api/staffs/": self.pelita["staff_id"],
            "/api/academic-years/": self.pelita["academic_year_id"],
            "/api/classes/": self.pelita["class_id"],
            "/api/class-teachers/": self.pelita["class_teacher_id"],
            "/api/students/": student["id"],
            "/api/guardians/": guardian_id,
            "/api/fee-types/": self.fee_type["id"],
            "/api/student-invoices/": self.invoice_id,
            "/api/payments/": self.payment["id"],
            "/api/activities/": self.activity["id"],
        }

    def test_outsiders_cannot_list_or_open_branch_records(self):
        # Control: the branch's own staff can open every record.
        for url, record_id in self.pelita_records().items():
            with self.subTest(insider="pelita staff", url=url):
                self.assert_status(self.pelita["staff_client"].get(f"{url}{record_id}/"), 200)

        for outsider, (client, _) in self.outsiders.items():
            for url, record_id in self.pelita_records().items():
                with self.subTest(outsider=outsider, url=url):
                    listing = client.get(url)
                    if listing.status_code == 200:
                        self.assertNotIn(record_id, [row["id"] for row in listing.data])
                    else:
                        self.assert_status(listing, 403)
                    self.assertIn(client.get(f"{url}{record_id}/").status_code, (403, 404))

    def test_other_school_cannot_see_school_or_users(self):
        client = self.harapan["staff_client"]
        schools = client.get("/api/schools/")
        self.assert_status(schools, 200)
        self.assertEqual([row["id"] for row in schools.data], [self.harapan["school_id"]])
        self.assert_status(client.get(f"/api/schools/{self.pelita['school_id']}/"), 404)

        for outsider, (client, _) in self.outsiders.items():
            with self.subTest(outsider=outsider):
                users = client.get("/api/users/")
                self.assert_status(users, 200)
                emails = {row["email"] for row in users.data}
                self.assertFalse(
                    emails & {"officer@pelita.test", "teacher@pelita.test", GUARDIAN_EMAIL},
                )

    def test_outsiders_cannot_write_into_branch(self):
        pelita = self.pelita
        today = str(timezone.localdate())
        for outsider, (client, own_branch_id) in self.outsiders.items():
            attempts = [
                ("post", "/api/academic-years/", {
                    "name": "Intruder Year", "branch": pelita["branch_id"],
                    "start_date": today, "end_date": today,
                }),
                ("post", "/api/staffs/", {
                    "branch": pelita["branch_id"], "first_name": "Intruder",
                    "email": f"intruder-{own_branch_id}@example.com", "staff_type": "officer",
                    "hire_date": today, "qualification": "None",
                }),
                ("post", "/api/classes/", {
                    "name": "Intruder Class", "branch": pelita["branch_id"],
                    "academic_year": pelita["academic_year_id"],
                }),
                ("post", "/api/students/", {
                    "first_name": "Intruder", "last_name": "Student",
                    "date_of_birth": "2019-01-01", "gender": "male",
                    "enroll_date": today, "status": "active",
                    "class_students": [{"class_id": pelita["class_id"]}],
                    "student_guardians": [{
                        "guardian_id": pelita["student"]["student_guardians"][0]["guardian_id"],
                        "relationship": "father", "is_primary": True,
                    }],
                }),
                ("post", "/api/fee-types/", {
                    "branch": own_branch_id, "name": "Intruder Fee", "amount": "1.00",
                    "class_ids": [pelita["class_id"]],
                }),
                ("post", f"/api/fee-types/{self.fee_type['id']}/generate-invoices/", {}),
                ("patch", f"/api/students/{pelita['student']['id']}/", {"first_name": "Changed"}),
                ("patch", f"/api/payments/{self.payment['id']}/", {"status": "completed"}),
                ("delete", f"/api/classes/{pelita['class_id']}/", None),
            ]
            for method, url, payload in attempts:
                with self.subTest(outsider=outsider, method=method, url=url):
                    response = getattr(client, method)(url, payload, format="json")
                    self.assertIn(response.status_code, (400, 403, 404), response.data)

        # Nothing in Pelita changed.
        staff_client = pelita["staff_client"]
        student = staff_client.get(f"/api/students/{pelita['student']['id']}/")
        self.assertEqual(student.data["first_name"], "Ayu")
        payment = staff_client.get(f"/api/payments/{self.payment['id']}/")
        self.assertEqual(payment.data["status"], "submitted")
        self.assert_status(staff_client.get(f"/api/classes/{pelita['class_id']}/"), 200)
        roster = staff_client.get(f"/api/classes/{pelita['class_id']}/students/")
        self.assertEqual(len(roster.data), 1)

    def test_guardian_of_other_school_sees_nothing_of_pelita(self):
        client, _ = self.login("guardian@harapan.test")
        for url, record_id in self.pelita_records().items():
            with self.subTest(url=url):
                listing = client.get(url)
                if listing.status_code == 200:
                    self.assertNotIn(record_id, [row["id"] for row in listing.data])
                self.assertIn(client.get(f"{url}{record_id}/").status_code, (403, 404))
