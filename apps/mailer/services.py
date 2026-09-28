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
        to_name,
        template_id,
        variables=None,
        subject=None,
    ):
        message = {
            "From": {
                "Email": settings.MAIL_FROM_EMAIL,
                "Name": settings.MAIL_FROM_NAME,
            },
            "To": [
                {
                    "Email": to_email,
                    "Name": to_name,
                }
            ],
            "TemplateID": template_id,
            "TemplateLanguage": True,
            "Variables": variables or {},
        }

        if subject:
            message["Subject"] = subject

        data = {
            "Messages": [message]
        }

        result = self.client.send.create(data=data)

        if result.status_code >= 400:
            raise Exception(
                f"Mailjet error {result.status_code}: {result.json()}"
            )

        print(result.json())

        return result.json()