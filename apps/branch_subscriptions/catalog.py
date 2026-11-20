"""
Classping's catalog: what a branch can buy. Loaded by migration 0002 (all
environments) and by `python manage.py seed subscriptions`. Only missing rows
are created; prices and limits are edited later in admin web → Plans.
"""
GB = 1024 ** 3
SAME_FOR_ALL_TIERS = {"payment_gateway": True}

CATALOG = {
    "features": [
        {"code": "max_students", "name": "Active students", "kind": "limit", "unit": "students", "on_expiry": "lock"},
        {"code": "storage_bytes", "name": "Image storage", "kind": "limit", "unit": "bytes", "on_expiry": "lock"},
        {"code": "payment_gateway", "name": "Online payment for parents", "kind": "boolean", "on_expiry": "lock"},
    ],
    "plans": [
        {
            "code": "starter", "name": "Starter", "sort_order": 1,
            "description": "Hingga 100 siswa · 50 GB",
            "prices": [{"interval": "month", "amount": "199000"}],
            "features": {"max_students": 100, "storage_bytes": 50 * GB, **SAME_FOR_ALL_TIERS},
        },
        {
            "code": "growth", "name": "Growth", "sort_order": 2,
            "description": "Hingga 300 siswa · 75 GB",
            "prices": [{"interval": "month", "amount": "449000"}],
            "features": {"max_students": 300, "storage_bytes": 75 * GB, **SAME_FOR_ALL_TIERS},
        },
        {
            "code": "pro", "name": "Pro", "sort_order": 3,
            "description": "Hingga 500 siswa · 100 GB",
            "prices": [{"interval": "month", "amount": "699000"}],
            "features": {"max_students": 500, "storage_bytes": 100 * GB, **SAME_FOR_ALL_TIERS},
        },
    ],
    "addons": [
        {
            # Price is a placeholder; set the real one in admin web → Plans → Add-ons.
            "code": "storage_10gb", "name": "Storage +10 GB", "billing": "recurring",
            "price": "50000", "max_quantity": 10,
            "features": [{"feature": "storage_bytes", "value": 10 * GB, "mode": "increment"}],
        },
    ],
}
