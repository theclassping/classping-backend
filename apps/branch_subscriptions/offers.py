"""What a branch can buy when it hits a limit (shown with the 403)."""
from plan_subscriptions.models import AddOn, AddOnFeature


def storage_offers():
    addons = []
    for addon in AddOn.objects.filter(is_active=True, addon_features__feature__code="storage_bytes").distinct():
        row = AddOnFeature.objects.filter(addon=addon, feature__code="storage_bytes").first()
        addons.append({
            "code": addon.code,
            "name": addon.name,
            "price": str(addon.price),
            "billing": addon.billing,
            "adds_bytes": row.value if row else None,
        })
    return {"addons": addons}
