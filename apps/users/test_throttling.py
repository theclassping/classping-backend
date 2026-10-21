from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from .models import User

LOCAL_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


@override_settings(CACHES=LOCAL_CACHE)
class AuthThrottlingTests(TestCase):
    password = "StrongPassword123!"

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            email="throttle@example.test",
            password=self.password,
            role=User.Role.ADMIN,
            is_superuser=True,
            is_staff=True,
        )
        self.client = APIClient()

    def post(self, url, data, **extra):
        return self.client.post(url, data, format="json", **extra)

    def login(self, email=None, password="WrongPassword123!", **extra):
        return self.post("/api/auth/login/", {
            "email": email or self.user.email, "password": password,
        }, **extra)

    def test_login_is_limited_per_account(self):
        for _ in range(5):
            self.assertEqual(self.login().status_code, 401)
        response = self.login(password=self.password)
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)
        # Email matching is case-insensitive, so casing cannot dodge the limit.
        self.assertEqual(self.login(email=self.user.email.upper()).status_code, 429)
        # Other accounts on the same IP are still allowed.
        self.assertEqual(self.login(email="other@example.test").status_code, 401)

    def test_login_is_limited_per_ip(self):
        with patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"login_ip": "3/min"}):
            for i in range(3):
                self.assertEqual(self.login(email=f"user{i}@example.test").status_code, 401)
            self.assertEqual(self.login(email="user9@example.test").status_code, 429)

    def test_forwarded_for_is_ignored_without_trusted_proxy(self):
        with patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"login_ip": "2/min"}):
            for i in range(2):
                self.login(email=f"user{i}@example.test", HTTP_X_FORWARDED_FOR=f"10.0.0.{i}")
            response = self.login(email="user9@example.test", HTTP_X_FORWARDED_FOR="10.0.0.9")
            self.assertEqual(response.status_code, 429)

    def test_trusted_proxy_uses_forwarded_client_ip(self):
        rest = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}
        with override_settings(REST_FRAMEWORK=rest), patch.dict(
            SimpleRateThrottle.THROTTLE_RATES, {"login_ip": "2/min"}
        ):
            for i in range(2):
                # A client-supplied first entry must not change the key.
                self.login(email=f"user{i}@example.test", HTTP_X_FORWARDED_FOR=f"1.1.1.{i}, 10.0.0.1")
            self.assertEqual(self.login(
                email="user8@example.test", HTTP_X_FORWARDED_FOR="10.0.0.1",
            ).status_code, 429)
            self.assertEqual(self.login(
                email="user9@example.test", HTTP_X_FORWARDED_FOR="10.0.0.2",
            ).status_code, 401)

    def test_refresh_is_limited(self):
        with patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"token_refresh": "2/min"}):
            for _ in range(2):
                self.assertEqual(self.post("/api/auth/refresh/", {"refresh": "bad"}).status_code, 401)
            self.assertEqual(self.post("/api/auth/refresh/", {"refresh": "bad"}).status_code, 429)

    def test_forgot_password_is_limited_per_account(self):
        for _ in range(3):
            self.assertEqual(self.post("/api/auth/forgot-password/", {"email": self.user.email}).status_code, 200)
        self.assertEqual(self.post("/api/auth/forgot-password/", {"email": self.user.email}).status_code, 429)
        self.assertEqual(self.post("/api/auth/forgot-password/", {"email": "other@example.test"}).status_code, 200)

    def test_reset_password_is_limited(self):
        data = {
            "uid": urlsafe_base64_encode(force_bytes(self.user.pk)),
            "token": "invalid-token",
            "new_password": "NewStrongPassword456!",
        }
        with patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"password_reset": "2/hour"}):
            for _ in range(2):
                self.assertEqual(self.post("/api/auth/reset-password/", data).status_code, 400)
            data["token"] = default_token_generator.make_token(self.user)
            self.assertEqual(self.post("/api/auth/reset-password/", data).status_code, 429)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.password))

    def test_change_password_is_limited_per_user(self):
        access = self.login(password=self.password).data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        data = {"old_password": "WrongPassword123!", "new_password": "NewStrongPassword456!"}
        for _ in range(5):
            self.assertEqual(self.post("/api/auth/change-password/", data).status_code, 400)
        data["old_password"] = self.password
        self.assertEqual(self.post("/api/auth/change-password/", data).status_code, 429)

    def test_admin_web_login_is_limited(self):
        data = {"email": self.user.email, "password": "WrongPassword123!"}
        for _ in range(5):
            self.assertEqual(self.client.post("/admin-web/login/", data).status_code, 200)
        response = self.client.post("/admin-web/login/", {**data, "password": self.password})
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "Too many login attempts", status_code=429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_django_admin_login_is_limited(self):
        data = {"username": self.user.email, "password": "WrongPassword123!"}
        for _ in range(5):
            self.assertEqual(self.client.post("/admin/login/", data).status_code, 200)
        response = self.client.post("/admin/login/", {**data, "password": self.password})
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("_auth_user_id", self.client.session)
