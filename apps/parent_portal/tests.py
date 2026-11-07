from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.core.testing import build_family, grant_parent_reads
from apps.users.models import RoleModulePermission, User

URL = "/api/parent/context/"


class ParentContextTests(TestCase):
    def setUp(self):
        # The existing endpoints are only used to compare response shapes.
        grant_parent_reads()
        self.user, self.guardian, self.students = build_family("ctx", children=2)
        self.other_user, _, self.other_students = build_family("other", children=1)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _get(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_parts_match_the_existing_endpoints(self):
        student = self.students[1]
        data = self._get(f"{URL}?student_id={student.pk}")
        current_class = student.class_students.get(is_current=True).class_obj

        self.assertEqual(set(data), {"students", "student", "current_class", "branch", "school"})
        self.assertEqual(data["students"], self._get("/api/students/"))
        self.assertEqual(data["student"], self._get(f"/api/students/{student.pk}/"))
        self.assertEqual(data["current_class"], self._get(f"/api/classes/{current_class.pk}/"))
        self.assertEqual(data["branch"], self._get(f"/api/branches/{current_class.branch_id}/"))
        self.assertEqual(data["school"], self._get(f"/api/schools/{current_class.branch.school_id}/"))

    def test_defaults_to_first_student_of_the_students_list(self):
        data = self._get(URL)

        self.assertEqual(data["student"]["id"], data["students"][0]["id"])
        self.assertEqual(data["student"]["id"], max(student.pk for student in self.students))

    def test_lists_only_the_guardians_own_students(self):
        data = self._get(URL)

        self.assertEqual(
            sorted(row["id"] for row in data["students"]),
            sorted(student.pk for student in self.students),
        )

    def test_class_only_lists_own_children(self):
        data = self._get(URL)
        ids = {row["student"]["id"] for row in data["current_class"]["class_students"]}

        self.assertTrue(ids <= {student.pk for student in self.students})

    def test_other_parents_student_is_not_found(self):
        response = self.client.get(f"{URL}?student_id={self.other_students[0].pk}")

        self.assertEqual(response.status_code, 404)

    def test_unknown_student_is_not_found(self):
        response = self.client.get(f"{URL}?student_id=999999")

        self.assertEqual(response.status_code, 404)

    def test_invalid_student_id_is_rejected(self):
        response = self.client.get(f"{URL}?student_id=abc")

        self.assertEqual(response.status_code, 400)
        self.assertIn("student_id", response.data)

    def test_student_without_current_class_falls_back_to_student_branch(self):
        student = self.students[0]
        student.class_students.update(is_current=False)

        data = self._get(f"{URL}?student_id={student.pk}")

        self.assertIsNone(data["current_class"])
        self.assertEqual(data["branch"]["id"], student.branch_id)
        self.assertEqual(data["school"]["id"], student.branch.school_id)

    def test_parent_without_students_gets_empty_context(self):
        lonely = User.objects.create_user(
            email="lonely-parent@example.test", password="StrongPassword123!", role="PARENT",
        )
        self.client.force_authenticate(lonely)

        self.assertEqual(self._get(URL), {
            "students": [], "student": None, "current_class": None, "branch": None, "school": None,
        })

    def test_only_parents_have_a_context(self):
        admin = User.objects.create_user(
            email="ctx-admin@example.test", password="StrongPassword123!", role="ADMIN",
        )
        RoleModulePermission.objects.filter(module="parent_portal", role="ADMIN").update(can_read=True)
        self.client.force_authenticate(admin)

        self.assertEqual(self.client.get(URL).status_code, 403)

    def test_requires_authentication(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)

    def test_read_grant_is_seeded_and_enforced(self):
        grant = RoleModulePermission.objects.get(role="PARENT", module="parent_portal")
        self.assertTrue(grant.can_read)
        self.assertFalse(grant.can_create or grant.can_edit or grant.can_delete)

        grant.can_read = False
        grant.save()
        self.assertEqual(self.client.get(URL).status_code, 403)

    def test_is_read_only(self):
        self.assertIn(self.client.post(URL, {}).status_code, (403, 405))

    def test_query_count_does_not_grow_with_children(self):
        large_user, _, _ = build_family("many", children=5)

        def count(user):
            client = APIClient()
            client.force_authenticate(user)
            with CaptureQueriesContext(connection) as queries:
                self.assertEqual(client.get(URL).status_code, 200)
            return len(queries)

        small, large = count(self.user), count(large_user)
        self.assertEqual(small, large)
        self.assertLessEqual(large, 20)
