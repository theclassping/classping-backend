from django.http import HttpResponseForbidden


class AdminWebRoleMiddleware:
    """Keep the platform-wide admin interface out of non-admin accounts."""

    exempt_paths = {
        "/admin-web/login/",
        "/admin-web/logout/",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not request.path.startswith("/admin-web/"):
            return None
        if request.path in self.exempt_paths or not request.user.is_authenticated:
            return None
        if request.user.is_superuser or str(request.user.role).upper() == "ADMIN":
            return None
        return HttpResponseForbidden()
