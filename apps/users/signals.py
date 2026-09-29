from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from apps.mailer.services import Mailer


@receiver(post_save, sender=get_user_model())
def email_new_user_account(sender, instance, created, **kwargs):
    if created and instance.email:
        temporary_password = getattr(instance, "_temporary_password", "")

        def send_welcome_email():
            uid = urlsafe_base64_encode(force_bytes(instance.pk))
            token = default_token_generator.make_token(instance)
            reset_url = (
                f"{settings.PASSWORD_RESET_URL}?uid={uid}&token={token}"
            )

            Mailer().send_template(
                to_email=instance.email,
                to_name=instance.full_name,
                template_id=settings.MAILJET_TEMPLATES["welcome_email"],
                variables={
                    "name": instance.full_name,
                    "email": instance.email,
                    "reset_url": reset_url,
                    "temporary_password": temporary_password,
                },
                subject="Akun Anda berhasil dibuat",
            )

        transaction.on_commit(
            send_welcome_email,
            robust=True,
        )