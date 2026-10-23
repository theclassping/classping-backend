from datetime import date
from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.test import TestCase
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from apps.locations.models import Location
from apps.schools.models import Branch, School
from apps.staffs.models import Staff
from apps.students.models import Student
from .models import RoleModulePermission, User
from .serializers import UserUpdateSerializer


class RoleManagementTests(TestCase):
    def setUp(self):
        import_module("apps.users.migrations.0007_account_management_permissions").update_permissions(apps, None)
        self.client = APIClient()
        self.accounts = {
            role: User.objects.create_user(email=f"{role}@example.test", password="StrongPassword123!", role=role)
            for role in User.Role.values
        }
        location = Location.objects.create(name="Province", code="RM", location_type="PROVINCE")
        school = School.objects.create(name="School", register_number="RM")
        self.branch = Branch.objects.create(school=school, location=location, name="Main", code="RM")
        self.other_branch = Branch.objects.create(school=school, location=location, name="Other", code="OTHER")
        for role in ("STAFF", "TEACHER"):
            Staff.objects.create(user=self.accounts[role], branch=self.branch, email=self.accounts[role].email,
                                 first_name=role, staff_type="teacher" if role == "TEACHER" else "officer",
                                 hire_date=date(2026, 1, 1), qualification="Education")
        self.student = Student.objects.create(branch=self.branch, first_name="Student", last_name="One",
                                              date_of_birth=date(2018, 1, 1), gender="male", enroll_date=date(2026, 1, 1))

    def payload(self, role):
        data = {"email": f"new-{role}@example.test", "password": "StrongPassword123!",
                "first_name": "New", "last_name": "Account", "role": role}
        if role == "PARENT":
            data["student_id"] = self.student.pk
        elif role in ("STAFF", "TEACHER"):
            data["staff_profile"] = {"branch": self.branch.pk, "staff_type": "teacher" if role == "TEACHER" else "officer",
                                     "hire_date": "2026-01-01", "qualification": "Education"}
        return data

    def test_staff_creation_matrix_and_scope(self):
        self.client.force_authenticate(self.accounts["STAFF"])
        for role in User.Role.values:
            with self.subTest(role=role):
                response = self.client.post("/api/users/", self.payload(role), format="json")
                self.assertEqual(response.status_code, 403 if role == "ADMIN" else 201, response.data)
                if role != "ADMIN":
                    created = User.objects.get(email=f"new-{role}@example.test")
                    self.assertEqual(self.client.get(f"/api/users/{created.pk}/").status_code, 200)

    def test_teacher_creation_requires_assigned_student(self):
        self.client.force_authenticate(self.accounts["TEACHER"])
        self.assertEqual(self.client.post("/api/users/", self.payload("PARENT"), format="json").status_code, 400)
        from apps.academic_years.models import AcademicYear
        from apps.classes.models import Class, ClassStudent, ClassTeacher
        year = AcademicYear.objects.create(branch=self.branch, name="2026", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))
        classroom = Class.objects.create(branch=self.branch, academic_year=year, name="One")
        ClassTeacher.objects.create(class_obj=classroom, staff=self.accounts["TEACHER"].staff)
        ClassStudent.objects.create(class_obj=classroom, student=self.student)
        response = self.client.post("/api/users/", self.payload("PARENT"), format="json")
        self.assertEqual(response.status_code, 201, response.data)
        parent = User.objects.get(email="new-PARENT@example.test")
        self.assertEqual(self.client.patch(f"/api/users/{parent.pk}/", {"first_name": "Updated"}, format="json").status_code, 200)
        self.assertEqual(self.client.patch(f"/api/users/{parent.pk}/", {"role": "STAFF"}, format="json").status_code, 403)
        for role in ("ADMIN", "STAFF", "TEACHER"):
            self.assertEqual(self.client.post("/api/users/", self.payload(role), format="json").status_code, 403)

    def test_update_checks_both_current_and_destination_role(self):
        allowed = {"ADMIN": set(User.Role.values), "STAFF": {"STAFF", "TEACHER", "PARENT"}, "TEACHER": {"PARENT"}, "PARENT": set()}
        for actor_role, actor in self.accounts.items():
            for target_role, target in self.accounts.items():
                for destination in User.Role.values:
                    with self.subTest(actor=actor_role, target=target_role, destination=destination):
                        serializer = UserUpdateSerializer(target, data={"role": destination}, partial=True,
                                                          context={"request": SimpleNamespace(user=actor)})
                        permitted = target_role in allowed[actor_role] and destination in allowed[actor_role]
                        if permitted:
                            self.assertTrue(serializer.is_valid(), serializer.errors)
                        elif actor_role == "PARENT" and target.pk == actor.pk:
                            self.assertFalse(serializer.is_valid())
                        else:
                            with self.assertRaises(PermissionDenied):
                                serializer.is_valid(raise_exception=True)

    def test_parent_cannot_escalate_even_with_module_permissions(self):
        RoleModulePermission.objects.filter(role="PARENT", module="users").update(can_create=True, can_edit=True, can_delete=True)
        parent = self.accounts["PARENT"]
        self.client.force_authenticate(parent)
        self.assertEqual(self.client.patch(f"/api/users/{parent.pk}/", {"role": "ADMIN"}, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/users/", self.payload("ADMIN"), format="json").status_code, 403)
        self.assertEqual(self.client.delete(f"/api/users/{parent.pk}/").status_code, 403)
        self.assertEqual(self.client.patch(f"/api/users/{parent.pk}/", {"first_name": "Updated"}, format="json").status_code, 200)

    def test_staff_cannot_create_in_other_branch(self):
        self.client.force_authenticate(self.accounts["STAFF"])
        data = self.payload("STAFF")
        data["staff_profile"]["branch"] = self.other_branch.pk
        self.assertEqual(self.client.post("/api/users/", data, format="json").status_code, 400)

    def test_admin_can_create_admin_and_change_roles(self):
        self.client.force_authenticate(self.accounts["ADMIN"])
        self.assertEqual(self.client.post("/api/users/", self.payload("ADMIN"), format="json").status_code, 201)
        target = self.accounts["PARENT"]
        self.assertEqual(self.client.patch(f"/api/users/{target.pk}/", {"role": "ADMIN"}, format="json").status_code, 200)
        target.refresh_from_db()
        self.assertEqual(target.role, "ADMIN")

    def test_staff_cannot_edit_account_in_another_branch(self):
        target = self.accounts["TEACHER"]
        Staff.objects.filter(user=target).update(branch=self.other_branch)
        self.client.force_authenticate(self.accounts["STAFF"])
        self.assertEqual(self.client.patch(f"/api/users/{target.pk}/", {"role": "STAFF"}, format="json").status_code, 404)

    def test_inline_guardian_cannot_modify_promoted_admin(self):
        from apps.guardians.models import Guardian
        from apps.students.serializers import StudentSerializer
        target = self.accounts["ADMIN"]
        guardian = Guardian.objects.create(user=target, name="Promoted", email=target.email)
        serializer = StudentSerializer(context={"request": SimpleNamespace(user=self.accounts["STAFF"])})
        with self.assertRaises(PermissionDenied):
            serializer._update_guardian(guardian, {"email": "taken@example.test"})
        target.refresh_from_db()
        self.assertEqual(target.email, "ADMIN@example.test")

    def test_staff_cannot_modify_privileged_account_through_staff_profile(self):
        target = self.accounts["TEACHER"]
        target.is_superuser = True
        target.save(update_fields=["is_superuser"])
        self.client.force_authenticate(self.accounts["STAFF"])
        response = self.client.patch(f"/api/staffs/{target.staff.pk}/", {"email": "taken@example.test"}, format="json")
        self.assertEqual(response.status_code, 403)
        target.refresh_from_db()
        self.assertEqual(target.email, "TEACHER@example.test")
