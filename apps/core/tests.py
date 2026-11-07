import re

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.core.testing import build_family, grant_parent_reads
from apps.schools.models import Branch, School
from apps.schools.serializers import BranchSerializer, SchoolSerializer
from apps.students.models import Student
from apps.students.serializers import StudentDetailSerializer, StudentSerializer

SERVER_TIMING = re.compile(r'^app;dur=\d+\.\d, db;dur=\d+\.\d;desc="(\d+) queries"$')


class ServerTimingMiddlewareTests(TestCase):
    def setUp(self):
        self.user, _, self.students = build_family("timing")
        grant_parent_reads()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_api_response_reports_server_time_and_query_count(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get("/api/students/")

        self.assertEqual(response.status_code, 200)
        match = SERVER_TIMING.match(response["Server-Timing"])
        self.assertIsNotNone(match, response["Server-Timing"])
        self.assertEqual(int(match.group(1)), len(queries))

    def test_error_responses_are_timed_too(self):
        response = APIClient().get("/api/students/")

        self.assertEqual(response.status_code, 401)
        self.assertRegex(response["Server-Timing"], SERVER_TIMING)

    def test_non_api_paths_are_not_timed(self):
        response = self.client.get("/admin-web/login/")

        self.assertNotIn("Server-Timing", response)

    @override_settings(SERVER_TIMING_ENABLED=False)
    def test_can_be_disabled(self):
        response = APIClient().get("/api/students/")

        self.assertNotIn("Server-Timing", response)

    def test_header_is_exposed_to_cross_origin_browsers(self):
        response = self.client.get("/api/students/", HTTP_ORIGIN="http://localhost:3000")

        self.assertIn("server-timing", response["Access-Control-Expose-Headers"].lower())


class ParentEndpointQueryCountTests(TestCase):
    """Parent-facing endpoints must not issue queries per row (N+1)."""

    def setUp(self):
        grant_parent_reads()
        self.small_user, _, self.small = build_family("small", children=1)
        self.large_user, _, self.large = build_family("large", children=4)

    def _count(self, user, url):
        client = APIClient()
        client.force_authenticate(user)
        with CaptureQueriesContext(connection) as queries:
            response = client.get(url)
        self.assertEqual(response.status_code, 200, (url, response.data))
        return len(queries)

    def _assert_constant(self, url_for):
        small = self._count(self.small_user, url_for(self.small[0]))
        large = self._count(self.large_user, url_for(self.large[0]))
        self.assertEqual(small, large, url_for(self.large[0]))

    def test_list_endpoints_do_not_grow_with_rows(self):
        for url in ("/api/students/", "/api/schools/", "/api/branches/", "/api/classes/",
                    "/api/student-invoices/", "/api/guardians/"):
            with self.subTest(url=url):
                self._assert_constant(lambda student, url=url: url)

    def test_student_scoped_endpoints_do_not_grow_with_rows(self):
        for template in ("/api/students/{}/", "/api/students/{}/invoices/",
                         "/api/student-invoices/?student_id={}", "/api/class-students/?student_id={}"):
            with self.subTest(url=template):
                self._assert_constant(lambda student, template=template: template.format(student.pk))

    def test_student_detail_query_budget(self):
        self.assertLessEqual(self._count(self.large_user, f"/api/students/{self.large[0].pk}/"), 8)

    def test_preloaded_lists_match_single_object_serialization(self):
        """Bulk-loaded list rows render exactly like the unoptimised per-row path."""
        client = APIClient()
        client.force_authenticate(self.large_user)

        students = client.get("/api/students/").json()
        expected = [StudentSerializer(Student.objects.get(pk=row["id"])).data for row in students]
        self.assertEqual(students, _json(expected))

        detail = client.get(f"/api/students/{self.large[0].pk}/").json()
        self.assertEqual(detail, _json(StudentDetailSerializer(Student.objects.get(pk=self.large[0].pk)).data))

        branches = client.get("/api/branches/").json()
        expected = [BranchSerializer(Branch.objects.get(pk=row["id"])).data for row in branches]
        self.assertEqual(branches, _json(expected))

        schools = client.get("/api/schools/").json()
        expected = [SchoolSerializer(School.objects.get(pk=row["id"])).data for row in schools]
        self.assertEqual(schools, _json(expected))


def _json(data):
    from rest_framework.renderers import JSONRenderer
    import json

    return json.loads(JSONRenderer().render(data))
