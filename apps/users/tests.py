from unittest.mock import patch

from django.test import TestCase, override_settings

from .managers import generate_temporary_password
from .models import User


@override_settings(MAILJET_TEMPLATES={"welcome_email": 1})
class TemporaryPasswordTests(TestCase):
	@patch("apps.users.signals.Mailer")
	def test_generated_password_is_stored_and_emailed(self, mailer_class):
		temporary_password = generate_temporary_password()

		with self.captureOnCommitCallbacks(execute=True):
			user = User.objects.create_user(
				email="parent@example.com",
				temporary_password=temporary_password,
				first_name="Pat",
				last_name="Parent",
				role=User.Role.PARENT,
			)

		self.assertTrue(user.check_password(temporary_password))
		variables = mailer_class.return_value.send_template.call_args.kwargs[
			"variables"
		]
		self.assertEqual(variables["temporary_password"], temporary_password)

	@patch("apps.users.signals.Mailer")
	def test_chosen_password_is_not_sent_as_temporary(self, mailer_class):
		chosen_password = "UserChosenPassword123!"

		with self.captureOnCommitCallbacks(execute=True):
			user = User.objects.create_user(
				email="staff@example.com",
				password=chosen_password,
				first_name="Sam",
				last_name="Staff",
				role=User.Role.STAFF,
			)

		self.assertTrue(user.check_password(chosen_password))
		variables = mailer_class.return_value.send_template.call_args.kwargs[
			"variables"
		]
		self.assertEqual(variables["temporary_password"], "")
