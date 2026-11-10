from django.db import migrations

# STAFF may POST gateway/payments/{id}/cancel/ (module "payment_gateway",
# create grant). The service still limits it to the branch's officer /
# principal.


def grant(apps, schema_editor):
    apps.get_model("users", "RoleModulePermission").objects.filter(
        role="STAFF", module="payment_gateway"
    ).update(can_create=True)


def revoke(apps, schema_editor):
    apps.get_model("users", "RoleModulePermission").objects.filter(
        role="STAFF", module="payment_gateway"
    ).update(can_create=False)


class Migration(migrations.Migration):
    dependencies = [("users", "0010_payment_gateway_module")]
    operations = [migrations.RunPython(grant, revoke)]
