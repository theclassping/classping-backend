from django.test import TestCase
from django.urls import reverse

from apps.academic_years.models import AcademicYear
from apps.classes.models import Class, ClassStudent
from apps.fee_types.models import FeeType, FeeTypeClass
from apps.guardians.models import Guardian
from apps.locations.models import Location
from apps.payments.models import Payment, PaymentProof
from apps.schools.models import Branch, School
from apps.score_settings.models import NumericScore, ScoreSetting
from apps.student_invoices.models import StudentInvoice
from apps.students.models import Student, StudentGuardian
from apps.users.models import RoleModulePermission, User


class RolePermissionAdminTests(TestCase):
	def setUp(self):
		self.url = reverse("admin_web:role_permissions")

	def test_only_platform_superusers_can_open_permissions(self):
		user = User.objects.create_user(
			email="school-user@example.com",
			password="StrongPassword123!",
			role=User.Role.TEACHER,
		)
		self.client.force_login(user)

		self.assertEqual(self.client.get(self.url).status_code, 403)

	def test_platform_superuser_can_update_role_permissions(self):
		admin = User.objects.create_superuser(
			email="platform-admin@example.com",
			password="StrongPassword123!",
			first_name="Platform",
			last_name="Admin",
		)
		self.client.force_login(admin)

		response = self.client.post(
			self.url,
			{
				"role": User.Role.PARENT,
				"activities_can_read": "on",
			},
		)

		self.assertEqual(response.status_code, 302)
		permission = RoleModulePermission.objects.get(
			role=User.Role.PARENT,
			module="activities",
		)
		self.assertTrue(permission.can_read)
		self.assertFalse(permission.can_create)
		self.assertFalse(permission.can_edit)
		self.assertFalse(permission.can_delete)


class AdminModulePageTests(TestCase):
	def setUp(self):
		admin = User.objects.create_superuser(
			email="module-admin@example.com",
			password="StrongPassword123!",
			first_name="Module",
			last_name="Admin",
		)
		self.client.force_login(admin)

	def test_activity_and_payment_pages_render(self):
		self.assertEqual(self.client.get("/admin-web/activities/").status_code, 200)
		self.assertEqual(self.client.get("/admin-web/payments/").status_code, 200)
		self.assertEqual(self.client.get("/admin-web/student-invoices/").status_code, 200)

	def test_platform_dashboard_filters_render(self):
		response = self.client.get("/admin-web/", {"school": 999999, "period": "month"})
		self.assertEqual(response.status_code, 200)

	def test_people_directory_pages_render(self):
		for path in ("/admin-web/students/", "/admin-web/guardians/"):
			with self.subTest(path=path):
				self.assertEqual(self.client.get(path).status_code, 200)
		self.assertNotContains(self.client.get("/admin-web/students/"), "/admin-web/teachers/")

	def test_student_and_guardian_forms_render(self):
		self.assertEqual(self.client.get("/admin-web/students/add/").status_code, 200)
		self.assertEqual(self.client.get("/admin-web/guardians/add/").status_code, 200)

	def test_school_class_and_payment_create_forms_render(self):
		location = Location.objects.create(name="Form Province", location_type="PROVINCE")
		school = School.objects.create(name="Form School", register_number="FORM-001")
		Branch.objects.create(
			school=school,
			name="Form Branch",
			code="FORM",
			location=location,
		)
		for path in (
			"/admin-web/schools/add/",
			f"/admin-web/schools/{school.pk}/edit/",
			f"/admin-web/schools/{school.pk}/classes/add/",
			"/admin-web/payments/add/",
		):
			with self.subTest(path=path):
				self.assertEqual(self.client.get(path).status_code, 200)

	def test_class_and_fee_type_crud(self):
		location = Location.objects.create(name="CRUD Province", location_type="PROVINCE")
		school = School.objects.create(name="CRUD School", register_number="CRUD-001")
		branch = Branch.objects.create(
			school=school,
			name="CRUD Branch",
			code="CRUD",
			location=location,
		)
		academic_year = AcademicYear.objects.create(
			name="2026",
			start_date="2026-01-01",
			end_date="2026-12-31",
			branch=branch,
		)
		class_response = self.client.post(
			reverse("admin_web:class_create", args=[school.pk]),
			{
				"name": "Primary A",
				"branch": branch.pk,
				"academic_year": academic_year.pk,
			},
		)
		self.assertEqual(class_response.status_code, 302)
		class_obj = Class.objects.get(name="Primary A")
		self.assertEqual(class_obj.branch_id, branch.pk)

		class_response = self.client.post(
			reverse("admin_web:class_edit", args=[school.pk, class_obj.pk]),
			{
				"name": "Primary B",
				"branch": branch.pk,
				"academic_year": academic_year.pk,
			},
		)
		self.assertEqual(class_response.status_code, 302)
		class_obj.refresh_from_db()
		self.assertEqual(class_obj.name, "Primary B")

		fee_response = self.client.post(
			"/admin-web/settings/fee-types/add/",
			{
				"branch": branch.pk,
				"name": "Tuition",
				"description": "Term tuition",
				"amount": "125.00",
				"currency": "IDR",
				"is_recurring": "",
				"is_active": "on",
				"classes": [class_obj.pk],
			},
		)
		self.assertEqual(fee_response.status_code, 302)
		fee_type = FeeType.objects.get(name="Tuition")
		self.assertTrue(FeeTypeClass.objects.filter(fee_type=fee_type, class_obj=class_obj).exists())
		self.client.post(reverse("admin_web:settings_delete", args=["fee-types", fee_type.pk]))
		fee_type.refresh_from_db()
		self.assertFalse(fee_type.is_active)
		self.client.post(
			reverse("admin_web:settings_edit", args=["fee-types", fee_type.pk]),
			{
				"branch": branch.pk,
				"name": fee_type.name,
				"description": fee_type.description,
				"amount": fee_type.amount,
				"currency": fee_type.currency,
				"is_recurring": "",
				"classes": [],
			},
		)
		self.assertFalse(FeeTypeClass.objects.filter(fee_type=fee_type).exists())

		self.client.post(reverse("admin_web:class_delete", args=[school.pk, class_obj.pk]))
		self.assertFalse(Class.objects.filter(pk=class_obj.pk).exists())

	def test_unverified_payment_and_proof_crud(self):
		location = Location.objects.create(name="Payment Province", location_type="PROVINCE")
		school = School.objects.create(name="Payment School", register_number="PAY-001")
		branch = Branch.objects.create(
			school=school,
			name="Payment Branch",
			code="PAY",
			location=location,
		)
		academic_year = AcademicYear.objects.create(
			name="2026",
			start_date="2026-01-01",
			end_date="2026-12-31",
			branch=branch,
		)
		class_obj = Class.objects.create(
			name="Payment Class",
			branch=branch,
			academic_year=academic_year,
		)
		student = Student.objects.create(
			first_name="Pay",
			last_name="Student",
			date_of_birth="2019-01-01",
			gender="other",
			enroll_date="2026-01-01",
		)
		class_student = ClassStudent.objects.create(
			student=student,
			class_obj=class_obj,
			is_current=True,
		)
		fee_type = FeeType.objects.create(
			branch=branch,
			name="One-time fee",
			amount="100.00",
		)
		invoice = StudentInvoice.objects.create(
			class_student=class_student,
			fee_type=fee_type,
			invoice_no="PAY-INV-001",
			invoice_date="2026-01-01",
			due_date="2026-01-31",
			subtotal="100.00",
			total_amount="100.00",
		)
		proof_data = {
			"proofs-TOTAL_FORMS": "1",
			"proofs-INITIAL_FORMS": "0",
			"proofs-MIN_NUM_FORMS": "0",
			"proofs-MAX_NUM_FORMS": "1000",
			"proofs-0-image_data": '{"object_key":"proofs/payment.png"}',
		}
		payment_data = {
			"student_invoice": invoice.pk,
			"amount": "100.00",
			"payment_method": "bank_transfer",
			**proof_data,
		}
		response = self.client.post("/admin-web/payments/add/", payment_data)
		self.assertEqual(response.status_code, 302)
		payment = Payment.objects.get(student_invoice=invoice)
		proof = PaymentProof.objects.get(payment=payment)
		self.assertEqual(proof.image_data["object_key"], "proofs/payment.png")
		invoice.refresh_from_db()
		self.assertEqual(invoice.status, StudentInvoice.Status.PAYMENT_SUBMITTED)

		payment_data["amount"] = "95.00"
		payment_data["proofs-INITIAL_FORMS"] = "1"
		payment_data["proofs-0-id"] = str(proof.pk)
		payment_data["proofs-0-image_data"] = '{"object_key":"proofs/payment-updated.png"}'
		response = self.client.post(reverse("admin_web:payment_edit", args=[payment.pk]), payment_data)
		self.assertEqual(response.status_code, 302)
		payment.refresh_from_db()
		proof.refresh_from_db()
		self.assertEqual(str(payment.amount), "95.00")
		self.assertEqual(proof.image_data["object_key"], "proofs/payment-updated.png")

		self.client.post(reverse("admin_web:payment_delete", args=[payment.pk]))
		self.assertFalse(Payment.objects.filter(pk=payment.pk).exists())
		self.assertFalse(PaymentProof.objects.filter(pk=proof.pk).exists())
		invoice.refresh_from_db()
		self.assertEqual(invoice.status, StudentInvoice.Status.UNPAID)

	def test_location_academic_year_and_score_settings_crud(self):
		location_response = self.client.post(
			"/admin-web/settings/locations/add/",
			{"name": "Editable Province", "code": "EP", "location_type": "PROVINCE", "parent": ""},
		)
		self.assertEqual(location_response.status_code, 302)
		location = Location.objects.get(code="EP")
		location_response = self.client.post(
			reverse("admin_web:settings_edit", args=["locations", location.pk]),
			{"name": "Updated Province", "code": "UP", "location_type": "PROVINCE", "parent": ""},
		)
		self.assertEqual(location_response.status_code, 302)
		location.refresh_from_db()
		self.assertEqual(location.name, "Updated Province")
		self.client.post(reverse("admin_web:settings_delete", args=["locations", location.pk]))
		self.assertFalse(Location.objects.filter(pk=location.pk).exists())

		branch_location = Location.objects.create(name="Branch Province", location_type="PROVINCE")
		school = School.objects.create(name="Settings School", register_number="SETTINGS-001")
		branch = Branch.objects.create(
			school=school,
			name="Settings Branch",
			code="SETTINGS",
			location=branch_location,
		)
		year_response = self.client.post(
			"/admin-web/settings/academic-years/add/",
			{
				"branch": branch.pk,
				"name": "2026-27",
				"start_date": "2026-07-01",
				"end_date": "2027-06-30",
				"is_current": "on",
			},
		)
		self.assertEqual(year_response.status_code, 302)
		year = AcademicYear.objects.get(branch=branch)
		self.assertTrue(year.is_current)
		year_response = self.client.post(
			reverse("admin_web:settings_edit", args=["academic-years", year.pk]),
			{
				"branch": branch.pk,
				"name": "2026-28",
				"start_date": "2026-07-01",
				"end_date": "2028-06-30",
				"is_current": "",
			},
		)
		self.assertEqual(year_response.status_code, 302)
		year.refresh_from_db()
		self.assertEqual(year.name, "2026-28")
		self.client.post(reverse("admin_web:settings_delete", args=["academic-years", year.pk]))
		self.assertFalse(AcademicYear.objects.filter(pk=year.pk).exists())

		score_response = self.client.post(
			"/admin-web/settings/score-settings/add/",
			{
				"branch": branch.pk,
				"name": "Assessment Scale",
				"description": "Numeric then level scoring",
				"score_type": "NUMERIC",
				"min_score": "0",
				"max_score": "100",
			},
		)
		self.assertEqual(score_response.status_code, 302)
		score_setting = ScoreSetting.objects.get(name="Assessment Scale")
		self.assertEqual(str(score_setting.numeric_score.max_score), "100.00")
		score_response = self.client.post(
			reverse("admin_web:settings_edit", args=["score-settings", score_setting.pk]),
			{
				"branch": branch.pk,
				"name": "Assessment Scale",
				"description": "Updated level scoring",
				"score_type": "LEVEL",
				"levels": "Beginning\nDeveloping\nSecure",
			},
		)
		self.assertEqual(score_response.status_code, 302)
		self.assertFalse(NumericScore.objects.filter(score_setting=score_setting).exists())
		self.assertEqual(
			list(score_setting.level_scores.values_list("name", flat=True)),
			["Beginning", "Developing", "Secure"],
		)
		self.assertEqual(
			self.client.get(reverse("admin_web:settings_detail", args=["score-settings", score_setting.pk])).status_code,
			200,
		)
		self.client.post(reverse("admin_web:settings_delete", args=["score-settings", score_setting.pk]))
		self.assertFalse(ScoreSetting.objects.filter(pk=score_setting.pk).exists())

	def test_student_guardian_crud_and_class_review(self):
		location = Location.objects.create(name="Central Province", location_type="PROVINCE")
		school = School.objects.create(name="Central School", register_number="CENTRAL-001")
		branch = Branch.objects.create(
			school=school,
			name="Central Branch",
			code="CENTRAL",
			address="8 Class Road",
			location=location,
		)
		academic_year = AcademicYear.objects.create(
			name="2026",
			start_date="2026-01-01",
			end_date="2026-12-31",
			branch=branch,
		)
		class_obj = Class.objects.create(
			name="Kindergarten A",
			branch=branch,
			academic_year=academic_year,
		)
		parent_user = User.objects.create_user(
			email="parent@example.com",
			password="StrongPassword123!",
			first_name="Pat",
			last_name="Parent",
			role=User.Role.PARENT,
		)

		guardian_response = self.client.post(
			"/admin-web/guardians/add/",
			{
				"user": parent_user.pk,
				"name": "Pat Parent",
				"phone_number": "555-0100",
				"email": "parent@example.com",
			},
		)
		self.assertEqual(guardian_response.status_code, 302)
		guardian = Guardian.objects.get(user=parent_user)

		student_data = {
			"first_name": "Sam",
			"middle_name": "",
			"last_name": "Student",
			"nickname": "",
			"date_of_birth": "2019-04-05",
			"gender": "other",
			"address": "8 Class Road",
			"enroll_date": "2026-01-15",
			"status": "active",
			"current_class": class_obj.pk,
			"location": location.pk,
			"guardians-TOTAL_FORMS": "1",
			"guardians-INITIAL_FORMS": "0",
			"guardians-MIN_NUM_FORMS": "0",
			"guardians-MAX_NUM_FORMS": "1000",
			"guardians-0-guardian": str(guardian.pk),
			"guardians-0-relationship": "mother",
			"guardians-0-is_primary": "on",
		}
		student_response = self.client.post("/admin-web/students/add/", student_data)
		self.assertEqual(student_response.status_code, 302)
		student = Student.objects.get(first_name="Sam")
		self.assertTrue(
			StudentGuardian.objects.get(student=student, guardian=guardian).is_primary
		)
		self.assertTrue(
			ClassStudent.objects.get(student=student, class_obj=class_obj).is_current
		)

		school_response = self.client.get(f"/admin-web/schools/{school.pk}/")
		self.assertContains(school_response, "Kindergarten A")
		self.assertContains(school_response, "Central Branch")
		self.assertEqual(
			self.client.get(reverse("admin_web:class_detail", args=[class_obj.pk])).status_code,
			200,
		)
		student_list_response = self.client.get("/admin-web/students/")
		self.assertContains(student_list_response, "Central School / Central Branch")

		self.assertEqual(
			self.client.get(reverse("admin_web:student_detail", args=[student.pk])).status_code,
			200,
		)
		student_data["first_name"] = "Samuel"
		student_data["guardians-INITIAL_FORMS"] = "1"
		student_data["guardians-0-id"] = str(
			StudentGuardian.objects.get(student=student, guardian=guardian).pk
		)
		student_response = self.client.post(
			reverse("admin_web:student_edit", args=[student.pk]),
			student_data,
		)
		self.assertEqual(student_response.status_code, 302)
		student.refresh_from_db()
		self.assertEqual(student.first_name, "Samuel")

		guardian_data = {
			"user": parent_user.pk,
			"name": "Pat Updated",
			"phone_number": "555-0199",
			"email": "parent@example.com",
		}
		guardian_response = self.client.post(
			reverse("admin_web:guardian_edit", args=[guardian.pk]),
			guardian_data,
		)
		self.assertEqual(guardian_response.status_code, 302)
		guardian.refresh_from_db()
		self.assertEqual(guardian.name, "Pat Updated")
		self.assertEqual(
			self.client.get(reverse("admin_web:guardian_detail", args=[guardian.pk])).status_code,
			200,
		)

		self.client.post(reverse("admin_web:student_delete", args=[student.pk]))
		self.assertFalse(Student.objects.filter(pk=student.pk).exists())
		self.client.post(reverse("admin_web:guardian_delete", args=[guardian.pk]))
		self.assertFalse(Guardian.objects.filter(pk=guardian.pk).exists())
		self.assertTrue(User.objects.filter(pk=parent_user.pk).exists())

	def test_school_detail_displays_branch_address_and_location(self):
		location = Location.objects.create(
			name="North Province",
			location_type="PROVINCE",
		)
		school = School.objects.create(
			name="North School",
			register_number="NORTH-001",
		)
		branch = Branch.objects.create(
			school=school,
			name="Main Branch",
			code="MAIN",
			address="12 Learning Street",
			location=location,
		)

		response = self.client.get(f"/admin-web/schools/{school.pk}/")

		self.assertContains(response, "12 Learning Street")
		self.assertContains(response, "North Province")
		branch_response = self.client.get(
			reverse("admin_web:branch_detail", args=[school.pk, branch.pk])
		)
		self.assertContains(branch_response, "12 Learning Street")
		self.assertContains(branch_response, "North Province")

	def test_settings_subpages_render(self):
		for section in ("fee-types", "locations", "academic-years", "score-settings"):
			with self.subTest(section=section):
				response = self.client.get(f"/admin-web/settings/{section}/")
				self.assertEqual(response.status_code, 200)

	def test_activity_and_settings_create_forms_render(self):
		self.assertEqual(self.client.get("/admin-web/activities/add/").status_code, 200)
		for section in ("fee-types", "locations", "academic-years", "score-settings"):
			with self.subTest(section=section):
				response = self.client.get(f"/admin-web/settings/{section}/add/")
				self.assertEqual(response.status_code, 200)
