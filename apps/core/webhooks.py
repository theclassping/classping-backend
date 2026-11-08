"""
Generic inbound webhook: POST /api/webhooks/<source>/<event>/

Add a webhook = one line in WEBHOOK_HANDLERS. A handler receives
(raw_body: bytes, headers) and returns a JSON-able dict; it raises
InvalidWebhook when the signature/token is wrong. No JWT, no CSRF: each
handler verifies its own signature on the raw body (never re-serialized).
"""

from django.http import Http404, JsonResponse
from django.utils.module_loading import import_string
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

WEBHOOK_HANDLERS = {
    ("rintisan", "payment"): "apps.payment_gateway.services.handle_payment_callback",
    # Step 6: ("rintisan", "disbursement"): "apps.wallets.services.handle_disbursement_callback",
}


class InvalidWebhook(Exception):
    pass


@csrf_exempt
@require_POST
def webhook(request, source, event):
    path = WEBHOOK_HANDLERS.get((source, event))
    if path is None:
        raise Http404()
    try:
        body = import_string(path)(request.body, request.headers)
    except InvalidWebhook:
        return JsonResponse({"detail": "Invalid webhook.", "code": "INVALID_WEBHOOK"}, status=401)
    return JsonResponse(body)
