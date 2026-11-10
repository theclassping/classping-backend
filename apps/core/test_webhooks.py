from unittest import mock

from django.test import SimpleTestCase

from apps.core import webhooks


def echo_handler(raw_body, headers):
    return {"body": raw_body.decode(), "token": headers.get("x-callback-token")}


def rejecting_handler(raw_body, headers):
    raise webhooks.InvalidWebhook()


HANDLERS = {
    ("test", "echo"): "apps.core.test_webhooks.echo_handler",
    ("test", "reject"): "apps.core.test_webhooks.rejecting_handler",
}


@mock.patch.dict(webhooks.WEBHOOK_HANDLERS, HANDLERS, clear=True)
class WebhookViewTests(SimpleTestCase):
    def test_raw_body_and_headers_reach_handler(self):
        raw = '{"qr_name":"Toko \\u00d1","a":1}'
        response = self.client.post(
            "/api/webhooks/test/echo/", raw, content_type="application/json",
            HTTP_X_CALLBACK_TOKEN="secret",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"body": raw, "token": "secret"})

    def test_unknown_webhook_is_404(self):
        self.assertEqual(self.client.post("/api/webhooks/test/nope/", "{}", content_type="application/json").status_code, 404)

    def test_only_post(self):
        self.assertEqual(self.client.get("/api/webhooks/test/echo/").status_code, 405)

    def test_invalid_webhook_is_401(self):
        response = self.client.post("/api/webhooks/test/reject/", "{}", content_type="application/json")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "INVALID_WEBHOOK")

    def test_no_csrf_or_jwt_needed(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post("/api/webhooks/test/echo/", "{}", content_type="application/json").status_code, 200)
