from unittest.mock import patch

from django.contrib.auth.tokens import default_token_generator
from django.test import TestCase
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APIClient
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User


class PasswordRevocationTests(TestCase):
    old_password = "OldStrongPassword123!"
    new_password = "NewStrongPassword456!"

    def setUp(self):
        self.user = User.objects.create_user(
            email="password-revocation@example.test",
            password=self.old_password,
            role=User.Role.ADMIN,
        )
        self.client = APIClient()
        self.sessions = [self.login(self.old_password) for _ in range(2)]

    def login(self, password):
        self.client.credentials()
        response = self.client.post("/api/auth/login/", {
            "email": self.user.email, "password": password,
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def assert_old_sessions_revoked(self):
        for session in self.sessions:
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {session['access']}")
            self.assertEqual(self.client.get("/api/users/").status_code, 401)
            self.client.credentials()
            self.assertEqual(self.client.post("/api/auth/refresh/", {
                "refresh": session["refresh"],
            }, format="json").status_code, 401)
            jti = RefreshToken(session["refresh"], verify=False)["jti"]
            self.assertTrue(BlacklistedToken.objects.filter(token__jti=jti).exists())
        response = self.client.post("/api/auth/login/", {
            "email": self.user.email, "password": self.old_password,
        }, format="json")
        self.assertEqual(response.status_code, 401)
        new_session = self.login(self.new_password)
        self.assertEqual(self.client.post("/api/auth/refresh/", {
            "refresh": new_session["refresh"],
        }, format="json").status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {new_session['access']}")
        self.assertEqual(self.client.get("/api/users/").status_code, 200)

    def test_change_password_revokes_all_sessions(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.sessions[0]['access']}")
        response = self.client.post("/api/auth/change-password/", {
            "old_password": self.old_password, "new_password": self.new_password,
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_old_sessions_revoked()

    def test_reset_password_revokes_all_sessions(self):
        response = self.client.post("/api/auth/reset-password/", {
            "uid": urlsafe_base64_encode(force_bytes(self.user.pk)),
            "token": default_token_generator.make_token(self.user),
            "new_password": self.new_password,
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assert_old_sessions_revoked()

    def test_model_save_covers_admin_and_management_password_changes(self):
        self.user.set_password(self.new_password)
        self.user.save()
        self.assert_old_sessions_revoked()

    def test_untracked_stale_refresh_and_legacy_tokens_are_rejected(self):
        token = RefreshToken(self.sessions[0]["refresh"])
        # Signed tokens absent from OutstandingToken must also fail by claim.
        token["jti"] = "untracked-stale-token"
        self.user.set_password(self.new_password)
        self.user.save(update_fields=["password"])
        self.assertEqual(self.client.post("/api/auth/refresh/", {
            "refresh": str(token),
        }, format="json").status_code, 401)
        fresh = RefreshToken.for_user(self.user)
        del fresh[api_settings.REVOKE_TOKEN_CLAIM]
        self.assertEqual(self.client.post("/api/auth/refresh/", {
            "refresh": str(fresh),
        }, format="json").status_code, 401)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {fresh.access_token}")
        self.assertEqual(self.client.get("/api/users/").status_code, 401)

    def test_failed_password_change_preserves_sessions(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.sessions[0]['access']}")
        response = self.client.post("/api/auth/change-password/", {
            "old_password": "IncorrectPassword123!", "new_password": self.new_password,
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/api/users/").status_code, 200)
        self.assertFalse(BlacklistedToken.objects.filter(token__user=self.user).exists())

    def test_blacklist_failure_rolls_back_password(self):
        self.user.set_password(self.new_password)
        with patch("django.db.models.query.QuerySet.bulk_create", side_effect=RuntimeError("failure")):
            with self.assertRaises(RuntimeError):
                self.user.save(update_fields=["password"])
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))

    def test_profile_save_does_not_revoke_tokens(self):
        self.user.first_name = "Updated"
        self.user.save(update_fields=["first_name"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.sessions[0]['access']}")
        self.assertEqual(self.client.get("/api/users/").status_code, 200)
        self.assertFalse(BlacklistedToken.objects.filter(token__user=self.user).exists())
