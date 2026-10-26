from unittest import expectedFailure

from django.utils import timezone

from .base import GUARDIAN_EMAIL, IntegrationTestCase


class StudentClassMoveTests(IntegrationTestCase):
    """Moving a student keeps history in the old class and moves future work to the new one."""

    def setUp(self):
        super().setUp()
        self.school = self.create_new_school()
        school = self.school
        self.student_id = school["student"]["id"]
        self.old_class_id = school["class_id"]

        new_teacher, self.new_teacher_client = self.create_staff(
            school["staff_client"], school["branch_id"], "teacher.1b@pelita.test", "teacher", "Rina",
        )
        self.new_class_id, self.new_class_teacher_id = self.create_class(
            school["staff_client"], school["branch_id"], school["academic_year_id"],
            "Grade 1B", new_teacher["id"],
        )
        # A classmate keeps Grade 1A billable after the move.
        self.create_student(school["staff_client"], self.old_class_id, "Bima", "Saputra", "bima.parent@example.com")

        # History from before the move: an invoice and a published activity in 1A.
        _, created = self.bill_class(
            school["staff_client"], school["branch_id"], self.old_class_id, "Uniform",
        )
        self.assertEqual(created, 2)
        self.old_activity = self.create_activity(
            school["teacher_client"], school["class_teacher_id"], self.old_class_id, "Painting Day",
        )

        moved = school["staff_client"].patch(
            f"/api/students/{self.student_id}/",
            {"class_students": [{"class_id": self.new_class_id, "is_current": True}]},
            format="json",
        )
        self.assert_status(moved, 200)
        self.guardian_client, _ = self.login(GUARDIAN_EMAIL)

    def create_activity(self, client, class_teacher_id, class_id, name, expected=201):
        return self.post(client, "/api/activities/", {
            "class_teacher_id": class_teacher_id,
            "class_id": class_id,
            "name": name,
            "activity_date": str(timezone.localdate()),
            "is_publish": True,
            "student_ids": [self.student_id],
        }, expected=expected)

    def roster(self, client, class_id, **params):
        response = client.get("/api/class-students/", {"class_id": class_id, **params})
        self.assert_status(response, 200)
        return [row["student_id"] for row in response.data]

    def test_new_class_becomes_current_and_old_is_history(self):
        student = self.school["staff_client"].get(f"/api/students/{self.student_id}/")
        self.assert_status(student, 200)
        self.assertEqual(
            {row["class_id"]: row["is_current"] for row in student.data["class_students"]},
            {self.old_class_id: False, self.new_class_id: True},
        )
        self.assertIn(self.student_id, self.roster(self.new_teacher_client, self.new_class_id))
        self.assertNotIn(
            self.student_id,
            self.roster(self.school["staff_client"], self.old_class_id, is_current="true"),
        )

    def test_new_invoices_follow_the_new_class(self):
        staff_client = self.school["staff_client"]
        branch_id = self.school["branch_id"]

        _, old_class_count = self.bill_class(staff_client, branch_id, self.old_class_id, "1A Excursion")
        self.assertEqual(old_class_count, 1)  # Only Bima is still in 1A.
        _, new_class_count = self.bill_class(staff_client, branch_id, self.new_class_id, "1B Excursion")
        self.assertEqual(new_class_count, 1)

        # The guardian keeps the pre-move invoice and gets the new class's fee.
        invoices = self.guardian_client.get("/api/student-invoices/")
        self.assert_status(invoices, 200)
        self.assertEqual(
            sorted((row["fee_type"]["name"], row["class_name"]) for row in invoices.data),
            [("1B Excursion", "Grade 1B"), ("Uniform", "Grade 1A")],
        )

        # The pre-move invoice can still be paid and verified.
        uniform = next(row for row in invoices.data if row["fee_type"]["name"] == "Uniform")
        payment = self.pay_invoice(self.guardian_client, uniform["id"])
        verified = staff_client.patch(
            f"/api/payments/{payment['id']}/", {"status": "completed"}, format="json",
        )
        self.assert_status(verified, 200)

    def test_activities_follow_the_new_class(self):
        # The new teacher can include the student in 1B activities.
        self.create_activity(
            self.new_teacher_client, self.new_class_teacher_id, self.new_class_id, "Music Class",
        )

        # The guardian keeps the old activity and sees the new one.
        activities = self.guardian_client.get("/api/activities/")
        self.assert_status(activities, 200)
        self.assertEqual(
            sorted((row["name"], row["class_name"]) for row in activities.data),
            [("Music Class", "Grade 1B"), ("Painting Day", "Grade 1A")],
        )

    # Known gap: activity validation accepts any past class assignment, not
    # only the current one. Remove the marker once that is restricted.
    @expectedFailure
    def test_old_class_teacher_can_no_longer_add_the_student(self):
        self.create_activity(
            self.school["teacher_client"], self.school["class_teacher_id"], self.old_class_id,
            "Science Fair", expected=400,
        )

    # Known gap: teacher scoping in apps/core/access.py follows every class
    # assignment, so the previous teacher keeps access. Remove the marker
    # once teachers are limited to current students.
    @expectedFailure
    def test_old_class_teacher_no_longer_sees_the_student(self):
        old_teacher = self.school["teacher_client"]
        students = old_teacher.get("/api/students/")
        self.assert_status(students, 200)
        self.assertNotIn(self.student_id, [row["id"] for row in students.data])
        self.assert_status(old_teacher.get(f"/api/students/{self.student_id}/"), 404)
