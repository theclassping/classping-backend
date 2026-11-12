"""
Generic inbound webhooks:

    POST /api/webhooks/payment/                 any payment provider
    POST /api/webhooks/disbursement/            (sender found by signature)
    POST /api/webhooks/<source>/<event>/        e.g. /rintisan/payment/
    POST /api/webhooks/v1.0/debit/notify        SNAP-standard paths (DANA):
    POST /api/webhooks/v1.0/debit/emoney/transfer-bank/notify.htm
                                                same as payment / disbursement

Add a webhook = one line in WEBHOOK_HANDLERS. A handler receives
(raw_body: bytes, headers, **kwargs) and returns a JSON-able dict or a
WebhookReply; it raises InvalidWebhook when the signature/token is wrong. No
JWT, no CSRF: each handler verifies its own signature on the raw body (never
re-serialized). Payment-provider handlers also receive ``request_path`` (some
providers sign it).
"""

from django.http import Http404, JsonResponse
from django.utils.module_loading import import_string
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.payment_aggregator.aggregator import provider_names

# Provider-neutral: give these to every provider (/api/webhooks/<event>/).
# Each provider also keeps /api/webhooks/<provider>/<event>/ (already
# registered at Rintisan), also when it is not the active one.
PROVIDER_WEBHOOK_EVENTS = {
    "payment": "apps.payment_gateway.services.handle_payment_callback",
    "disbursement": "apps.wallets.services.handle_disbursement_callback",
}

# (source, event) -> "dotted.path" or ("dotted.path", kwargs)
WEBHOOK_HANDLERS = {
    (provider, event): (path, {"provider": provider})
    for provider in provider_names()
    for event, path in PROVIDER_WEBHOOK_EVENTS.items()
}


class InvalidWebhook(Exception):
    pass


class WebhookReply:
    """A handler result with its own body / headers / status (e.g. the
    acknowledgement format a provider requires)."""

    def __init__(self, body, headers=None, status=200):
        self.body = body
        self.headers = headers or {}
        self.status = status


@csrf_exempt
@require_POST
def webhook(request, source, event):
    handler = WEBHOOK_HANDLERS.get((source, event))
    # Provider routes are (path, kwargs) tuples; plain strings are other webhooks.
    return _dispatch(request, handler, provider_event=isinstance(handler, tuple))


@csrf_exempt
@require_POST
def provider_webhook(request, event):
    return _dispatch(request, PROVIDER_WEBHOOK_EVENTS.get(event), provider_event=True)


def _dispatch(request, handler, provider_event=False):
    if handler is None:
        raise Http404()
    path, kwargs = (handler, {}) if isinstance(handler, str) else handler
    if provider_event:
        kwargs = dict(kwargs, request_path=request.path)
    try:
        result = import_string(path)(request.body, request.headers, **kwargs)
    except InvalidWebhook:
        return JsonResponse({"detail": "Invalid webhook.", "code": "INVALID_WEBHOOK"}, status=401)
    if isinstance(result, WebhookReply):
        response = JsonResponse(result.body, status=result.status)
        for name, value in result.headers.items():
            response[name] = value
        return response
    return JsonResponse(result)
