from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from .models import RevokedTokenSession, User


class LogoutSessionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="logout-session@example.test", password="StrongPassword123!", role="ADMIN",
        )
        self.client = APIClient()

    def login(self, user=None):
        self.client.credentials()
        response = self.client.post("/api/auth/login/", {
            "email": (user or self.user).email, "password": "StrongPassword123!",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        return response.data

    def refresh(self, token):
        self.client.credentials()
        return self.client.post("/api/auth/refresh/", {"refresh": token}, format="json")

    def access_status(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return self.client.get("/api/users/").status_code

    def test_logout_revokes_original_and_all_refreshed_access_only_in_that_session(self):
        session = self.login()
        other_session = self.login()
        refreshed = [self.refresh(session["refresh"]).data["access"] for _ in range(2)]
        sid = AccessToken(session["access"])["sid"]
        self.assertTrue(all(AccessToken(token)["sid"] == sid for token in refreshed))
        self.assertNotEqual(sid, AccessToken(other_session["access"])["sid"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refreshed[0]}")
        response = self.client.post("/api/auth/logout/", {"refresh": session["refresh"]}, format="json")
        self.assertEqual(response.status_code, 205, response.data)
        for token in [session["access"], *refreshed]:
            self.assertEqual(self.access_status(token), 401)
        self.assertEqual(self.refresh(session["refresh"]).status_code, 401)
        self.assertEqual(self.access_status(other_session["access"]), 200)
        self.assertEqual(self.refresh(other_session["refresh"]).status_code, 200)

    def test_logout_rejects_refresh_from_other_session_or_other_user_without_revoking(self):
        session = self.login()
        another = self.login()
        user = User.objects.create_user(email="another@example.test", password="StrongPassword123!", role="ADMIN")
        foreign = self.login(user)
        for mismatch in (another, foreign):
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {session['access']}")
            response = self.client.post("/api/auth/logout/", {"refresh": mismatch["refresh"]}, format="json")
            self.assertEqual(response.status_code, 400)
        self.assertFalse(RevokedTokenSession.objects.exists())
        for valid in (session, another, foreign):
            self.assertEqual(self.access_status(valid["access"]), 200)
            self.assertEqual(self.refresh(valid["refresh"]).status_code, 200)

    def test_revoked_session_blocks_refresh_even_without_blacklist_entry(self):
        session = self.login()
        token = RefreshToken(session["refresh"])
        RevokedTokenSession.objects.create(sid=token["sid"], expires_at=self.user.created_at)
        self.assertEqual(self.refresh(session["refresh"]).status_code, 401)
        self.assertEqual(self.access_status(session["access"]), 401)

    def test_blacklist_failure_rolls_back_session_revocation(self):
        session = self.login()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {session['access']}")
        with patch("apps.users.serializers.LogoutSerializer.save", side_effect=RuntimeError("failure")):
            with self.assertRaises(RuntimeError):
                self.client.post("/api/auth/logout/", {"refresh": session["refresh"]}, format="json")
        self.assertFalse(RevokedTokenSession.objects.exists())
        self.assertEqual(self.access_status(session["access"]), 200)
