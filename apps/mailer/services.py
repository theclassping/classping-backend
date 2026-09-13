from django.conf import settings
from mailjet_rest import Client


class Mailer:
    def __init__(self):
        self.client = Client(
            auth=(
                settings.MAILJET_API_KEY,
                settings.MAILJET_API_SECRET,
            ),
            version="v3.1",
        )

    def send_template(
        self,
        *,
        to_email,
        to_name=None,
        template_id,
        variables=None,
    ):
        message = {
            "From": {
                "Email": settings.MAIL_FROM_EMAIL,
                "Name": settings.MAIL_FROM_NAME,
            },
            "To": [
                {
                    "Email": to_email,
                    **({"Name": to_name} if to_name else {}),
                }
            ],
            "TemplateID": template_id,
            "TemplateLanguage": True,
            "Variables": variables or {},
        }

        return self.client.send.create(
            data={
                "Messages": [message],
            }
        )