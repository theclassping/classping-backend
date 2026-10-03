from unittest.mock import patch

from django.test import TestCase, override_settings
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APITestCase, APIClient

from apps.users.serializers import LogoutSerializer
from apps.schools.models import Branch, School
from apps.locations.models import Location
from .managers import generate_temporary_password
from .models import User
from .models import RevokedAccessToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.tokens import AccessToken
from datetime import datetime, timedelta, timezone


@override_settings(MAILJET_TEMPLATES={"welcome_email": 1})
class TemporaryPasswordTests(TestCase):
	@patch("apps.users.signals.Mailer")
	def test_generated_password_is_stored_and_emailed(self, mailer_class):
		temporary_password = generate_temporary_password()

		with self.captureOnCommitCallbacks(execute=True):
			user = User.objects.create_user(
				email="parent@example.com",
				temporary_password=temporary_password,
				first_name="Pat",
				last_name="Parent",
				role=User.Role.PARENT,
			)

		self.assertTrue(user.check_password(temporary_password))
		variables = mailer_class.return_value.send_template.call_args.kwargs[
			"variables"
		]
		self.assertEqual(variables["temporary_password"], temporary_password)

	@patch("apps.users.signals.Mailer")
	def test_chosen_password_is_not_sent_as_temporary(self, mailer_class):
		chosen_password = "UserChosenPassword123!"

		with self.captureOnCommitCallbacks(execute=True):
			user = User.objects.create_user(
				email="staff@example.com",
				password=chosen_password,
				first_name="Sam",
				last_name="Staff",
				role=User.Role.STAFF,
			)

		self.assertTrue(user.check_password(chosen_password))
		variables = mailer_class.return_value.send_template.call_args.kwargs[
			"variables"
		]
		self.assertEqual(variables["temporary_password"], "")

	def test_logout_serializer_rejects_invalid_refresh_token(self):
		serializer = LogoutSerializer(data={"refresh": "not-a-valid-token"})

		self.assertFalse(serializer.is_valid())
		self.assertIn("refresh", serializer.errors)


class ProtectedApiAccessTests(APITestCase):
	"""Every protected API must reject anonymous requests consistently."""

	protected_get_urls = [
		"/api/users/",
		"/api/schools/",
		"/api/branches/",
		"/api/locations/",
		"/api/staffs/",
		"/api/academic-years/",
		"/api/classes/",
		"/api/class-teachers/",
		"/api/class-students/",
		"/api/students/",
		"/api/student-guardians/",
		"/api/guardians/",
		"/api/assessment-images/",
		"/api/activities/",
		"/api/activity-images/",
		"/api/activity-students/",
		"/api/fee-types/",
		"/api/student-invoices/",
		"/api/payments/",
		"/api/payment-proofs/",
		"/api/media/download/url/?file_key=missing.txt",
	]

	def test_all_protected_get_endpoints_require_authentication(self):
		for url in self.protected_get_urls:
			with self.subTest(url=url):
				response = self.client.get(url)
				self.assertEqual(response.status_code, 401)

	def test_protected_media_methods_require_authentication(self):
		cases = [
			("post", "/api/media/presign/", {}),
			("put", "/api/media/upload/example.txt", b"data"),
		]
		for method, url, body in cases:
			with self.subTest(method=method, url=url):
				if method == "put":
					response = self.client.generic(
						"PUT",
						url,
						data=body,
						content_type="application/octet-stream",
					)
				else:
					response = getattr(self.client, method)(url, body, format="json")
				self.assertEqual(response.status_code, 401)

class PublicAuthApiTests(APITestCase):
	def test_forgot_password_requires_valid_email(self):
		response = self.client.post("/api/auth/forgot-password/", {}, format="json")
		self.assertEqual(response.status_code, 400)

	def test_login_returns_access_and_refresh_tokens(self):
		User.objects.create_user(
			email="login@example.com",
			password="StrongPassword123!",
			role=User.Role.PARENT,
		)
		response = self.client.post(
			"/api/auth/login/",
			{"email": "login@example.com", "password": "StrongPassword123!"},
			format="json",
		)
		self.assertEqual(response.status_code, 200)
		self.assertIn("access", response.data)
		self.assertIn("refresh", response.data)

	def test_login_rejects_wrong_password(self):
		User.objects.create_user(
			email="wrong-password@example.com",
			password="StrongPassword123!",
			role=User.Role.PARENT,
		)
		response = self.client.post(
			"/api/auth/login/",
			{"email": "wrong-password@example.com", "password": "WrongPassword123!"},
			format="json",
		)
		self.assertEqual(response.status_code, 401)

	def test_inactive_user_cannot_login(self):
		User.objects.create_user(
			email="inactive@example.com", password="StrongPassword123!",
			role=User.Role.PARENT, is_active=False,
		)
		response = self.client.post(
			"/api/auth/login/",
			{"email": "inactive@example.com", "password": "StrongPassword123!"},
			format="json",
		)
		self.assertEqual(response.status_code, 401)

	def test_invalid_access_token_is_rejected(self):
		self.client.credentials(HTTP_AUTHORIZATION="Bearer invalid.token.value")
		response = self.client.get("/api/locations/")
		self.assertEqual(response.status_code, 401)

	def test_expired_access_token_is_rejected(self):
		user = User.objects.create_user(
			email="expired@example.com", password="StrongPassword123!", role=User.Role.PARENT,
		)
		token = AccessToken.for_user(user)
		token["exp"] = int((datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp())
		self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(token)}")
		response = self.client.get("/api/locations/")
		self.assertEqual(response.status_code, 401)

	def test_refresh_returns_new_access_token(self):
		user = User.objects.create_user(
			email="refresh@example.com",
			password="StrongPassword123!",
			role=User.Role.PARENT,
		)
		login = self.client.post(
			"/api/auth/login/",
			{"email": user.email, "password": "StrongPassword123!"},
			format="json",
		)
		response = self.client.post(
			"/api/auth/refresh/",
			{"refresh": login.data["refresh"]},
			format="json",
		)
		self.assertEqual(response.status_code, 200)
		self.assertIn("access", response.data)

	@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
	def test_forgot_password_sends_reset_email_for_existing_user(self):
		user = User.objects.create_user(
			email="forgot@example.com",
			password="StrongPassword123!",
			role=User.Role.PARENT,
		)
		response = self.client.post(
			"/api/auth/forgot-password/",
			{"email": user.email},
			format="json",
		)
		self.assertEqual(response.status_code, 200)

	def test_reset_password_accepts_valid_token(self):
		user = User.objects.create_user(
			email="reset@example.com",
			password="OldPassword123!",
			role=User.Role.PARENT,
		)
		uid = urlsafe_base64_encode(force_bytes(user.pk))
		token = default_token_generator.make_token(user)
		response = self.client.post(
			"/api/auth/reset-password/",
			{"uid": uid, "token": token, "new_password": "NewPassword123!"},
			format="json",
		)
		self.assertEqual(response.status_code, 200)
		user.refresh_from_db()
		self.assertTrue(user.check_password("NewPassword123!"))

	def test_logout_revokes_access_token_and_blacklists_refresh_token(self):
		user = User.objects.create_user(
			email="logout@example.com",
			password="StrongPassword123!",
			role=User.Role.PARENT,
		)
		login = self.client.post(
			"/api/auth/login/",
			{"email": user.email, "password": "StrongPassword123!"},
			format="json",
		)
		self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
		response = self.client.post(
			"/api/auth/logout/", {"refresh": login.data["refresh"]}, format="json"
		)
		self.assertEqual(response.status_code, 205)
		self.assertTrue(RevokedAccessToken.objects.exists())
		refresh_response = self.client.post(
			"/api/auth/refresh/", {"refresh": login.data["refresh"]}, format="json"
		)
		self.assertEqual(refresh_response.status_code, 401)


class BasicCrudApiTests(APITestCase):
	def setUp(self):
		self.user = User.objects.create_user(
			email="api-tester@example.com",
			password="StrongPassword123!",
			first_name="API",
			last_name="Tester",
			role=User.Role.ADMIN,
		)
		self.client.force_authenticate(user=self.user)

	def test_create_and_retrieve_user(self):
		response = self.client.post(
			"/api/users/",
			{
				"email": "created@example.com",
				"password": "AnotherStrong123!",
				"first_name": "Created",
				"last_name": "User",
				"role": User.Role.PARENT,
			},
			format="json",
		)
		self.assertEqual(response.status_code, 201)
		self.assertNotIn("password", response.data)
		self.assertEqual(response.data["email"], "created@example.com")

	def test_create_school_and_update_it(self):
		response = self.client.post(
			"/api/schools/",
			{"name": "API School", "register_number": "API-001", "is_active": True},
			format="json",
		)
		self.assertEqual(response.status_code, 201)
		school_id = response.data["id"]

		response = self.client.patch(
			f"/api/schools/{school_id}/",
			{"name": "Updated API School"},
			format="json",
		)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data["name"], "Updated API School")

	def test_create_academic_year(self):
		school = School.objects.create(name="Academic School", register_number="AY-001")
		location = Location.objects.create(
			name="Test Province",
			code="TP",
			location_type="PROVINCE",
		)
		branch = Branch.objects.create(
			school=school,
			name="Main Branch",
			code="MAIN",
			location=location,
		)
		response = self.client.post(
			"/api/academic-years/",
			{
				"name": "2026/2027",
				"start_date": "2026-07-01",
				"end_date": "2027-06-30",
				"is_current": True,
				"branch": branch.id,
			},
			format="json",
		)
		self.assertEqual(response.status_code, 201)
		self.assertEqual(response.data["name"], "2026/2027")

	def test_invalid_school_payload_is_rejected(self):
		response = self.client.post(
			"/api/schools/",
			{"name": "Missing Register Number"},
			format="json",
		)
		self.assertEqual(response.status_code, 400)

	def test_authenticated_resource_collections_return_success(self):
		urls = [
			"/api/users/", "/api/schools/", "/api/branches/",
			"/api/locations/", "/api/staffs/", "/api/academic-years/",
			"/api/classes/", "/api/class-teachers/", "/api/class-students/",
			"/api/students/", "/api/student-guardians/", "/api/guardians/",
			"/api/assessment-images/", "/api/activities/",
			"/api/activity-images/", "/api/activity-students/",
			"/api/fee-types/", "/api/student-invoices/", "/api/payments/",
			"/api/payment-proofs/",
		]
		for url in urls:
			with self.subTest(url=url):
				response = self.client.get(url)
				self.assertEqual(response.status_code, 200)

	def test_invalid_detail_ids_return_not_found(self):
		urls = [
			"/api/users/999999/", "/api/schools/999999/",
			"/api/branches/999999/", "/api/staffs/999999/",
			"/api/academic-years/999999/", "/api/classes/999999/",
			"/api/students/999999/", "/api/guardians/999999/",
			"/api/activities/999999/", "/api/fee-types/999999/",
			"/api/student-invoices/999999/", "/api/payments/999999/",
		]
		for url in urls:
			with self.subTest(url=url):
				response = self.client.get(url)
				self.assertEqual(response.status_code, 404)

	def test_reset_password_requires_all_fields(self):
		response = self.client.post("/api/auth/reset-password/", {}, format="json")
		self.assertEqual(response.status_code, 400)
