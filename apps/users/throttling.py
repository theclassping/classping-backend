"""Rate limits for login and password endpoints.

Rates live in REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]. Counters are stored in
the default cache, which must be shared by every worker (Redis in production).
"""
import hashlib
from functools import wraps

from django.http import HttpResponse
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle


def _submitted_email(request):
    # DRF requests expose parsed bodies as .data; Django form views use .POST.
    data = getattr(request, "data", None) or request.POST
    return str(data.get("email") or data.get("username") or "").strip().lower()


class IPRateThrottle(SimpleRateThrottle):
    """Limit by client IP, whether or not the request is authenticated."""

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class EmailRateThrottle(SimpleRateThrottle):
    """Limit attempts against one account, however many IPs they come from."""

    def get_cache_key(self, request, view):
        email = _submitted_email(request)
        if not email:
            return None
        # Hash so cache keys never contain addresses.
        ident = hashlib.sha256(email.encode()).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": ident}


class LoginIPThrottle(IPRateThrottle):
    scope = "login_ip"


class LoginEmailThrottle(EmailRateThrottle):
    scope = "login_email"


class TokenRefreshThrottle(IPRateThrottle):
    scope = "token_refresh"


class ForgotPasswordIPThrottle(IPRateThrottle):
    scope = "password_forgot_ip"


class ForgotPasswordEmailThrottle(EmailRateThrottle):
    scope = "password_forgot_email"


class ResetPasswordThrottle(IPRateThrottle):
    scope = "password_reset"


class ChangePasswordThrottle(UserRateThrottle):
    scope = "password_change"


LOGIN_THROTTLES = [LoginIPThrottle, LoginEmailThrottle]


def login_throttle_wait(request):
    """Apply the API login limits to a session login form submission.

    Returns the seconds to wait when the attempt is refused, otherwise None.
    """
    waits = []
    for throttle_class in LOGIN_THROTTLES:
        throttle = throttle_class()
        if not throttle.allow_request(request, None):
            waits.append(throttle.wait() or 0)
    return max(waits) if waits else None


def throttle_login_form(view):
    """Refuse POSTs to a session login view once the login limits are hit."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.method == "POST":
            wait = login_throttle_wait(request)
            if wait is not None:
                response = HttpResponse(
                    "Too many login attempts. Please try again later.",
                    status=429,
                    content_type="text/plain",
                )
                response["Retry-After"] = str(int(wait))
                return response
        return view(request, *args, **kwargs)

    return wrapped
