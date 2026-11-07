from django.test import SimpleTestCase

from apps.core.phone import InvalidPhoneNumber, normalize_phone


class NormalizePhoneTests(SimpleTestCase):
    def test_local_and_international_formats(self):
        cases = {
            "081234567890": "6281234567890",
            "0812-3456-7890": "6281234567890",
            "+62 812 3456 7890": "6281234567890",
            "6281234567890": "6281234567890",
            "(+62) 812.3456.7890": "6281234567890",
            "+65 9123 4567": "6591234567",
        }
        for raw, expected in cases.items():
            self.assertEqual(normalize_phone(raw), expected, msg=raw)

    def test_invalid_numbers(self):
        for raw in (None, "", "123", "abc", "0812", "1234567890123456"):
            with self.assertRaises(InvalidPhoneNumber, msg=repr(raw)):
                normalize_phone(raw)
