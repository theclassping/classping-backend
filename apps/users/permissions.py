from rest_framework.permissions import IsAuthenticated

from .models import RoleModulePermission


class RoleBasedAccessPermission(IsAuthenticated):
	"""Apply configured module actions after normal authentication."""

	def has_permission(self, request, view):
		if not super().has_permission(request, view):
			return False

		if request.user.is_superuser:
			return True

		module = view.__class__.__module__.split(".")[1]
		if request.method in ("GET", "HEAD", "OPTIONS"):
			permission_field = "can_read"
		elif request.method == "POST":
			permission_field = "can_create"
		elif request.method in ("PUT", "PATCH"):
			permission_field = "can_create" if module == "uploads" else "can_edit"
		elif request.method == "DELETE":
			permission_field = "can_delete"
		else:
			return False

		return RoleModulePermission.objects.filter(
			role=request.user.role,
			module=module,
			**{permission_field: True},
		).exists()
