from datetime import date, timedelta
from decimal import Decimal

from apps.classes.models import Class, ClassStudent
from apps.fee_types.models import FeeType, FeeTypeClass
from apps.schools.models import Branch
from apps.student_invoices.models import StudentInvoice


def seed_billing():
    branch = Branch.objects.get(name="Main Campus")
    classes = {
        class_obj.name: class_obj
        for class_obj in Class.objects.filter(branch=branch)
    }

    fee_types = {}
    fee_type_data = [
        {
            "name": "Monthly Tuition",
            "description": "Monthly tuition fee for selected classes.",
            "amount": Decimal("500000.00"),
            "currency": "IDR",
            "is_recurring": True,
            "recurring_frequency": FeeType.RecurringFrequency.MONTHLY,
        },
        {
            "name": "Uniform",
            "description": "School uniform fee.",
            "amount": Decimal("350000.00"),
            "currency": "IDR",
            "is_recurring": False,
            "recurring_frequency": None,
        },
        {
            "name": "Field Trip",
            "description": "Field trip contribution.",
            "amount": Decimal("250000.00"),
            "currency": "IDR",
            "is_recurring": False,
            "recurring_frequency": None,
        },
        {
            "name": "Dummy Fee",
            "description": "Dummy fee used for payment and invoice testing.",
            "amount": Decimal("500000.00"),
            "currency": "IDR",
            "is_recurring": True,
            "recurring_frequency": FeeType.RecurringFrequency.MONTHLY,
        },
    ]

    for data in fee_type_data:
        fee_type, _ = FeeType.objects.update_or_create(
            branch=branch,
            name=data["name"],
            defaults=data,
        )
        fee_types[fee_type.name] = fee_type

    # Monthly fees apply only to selected classes.
    for fee_name in ["Monthly Tuition", "Dummy Fee"]:
        fee_type = fee_types[fee_name]
        for class_name in ["Class A", "Class B"]:
            if class_name in classes:
                FeeTypeClass.objects.get_or_create(
                    fee_type=fee_type,
                    class_obj=classes[class_name],
                )

    class_students = list(
        ClassStudent.objects.filter(
            class_obj__branch=branch,
            class_obj__name__in=["Class A", "Class B"],
        ).select_related("student", "class_obj")[:2]
    )

    if len(class_students) < 2:
        return

    for class_student in class_students:
        if not class_student.is_current:
            class_student.is_current = True
            class_student.save(update_fields=["is_current"])

    dummy_fee = fee_types["Dummy Fee"]
    today = date.today()

    invoice_data = [
        {
            "class_student": class_students[0],
            "invoice_date": today,
            "due_date": today + timedelta(days=14),
            "status": StudentInvoice.Status.UNPAID,
            "invoice_no": f"INV-SEED-UNPAID-{class_students[0].student_id}",
        },
        {
            "class_student": class_students[1],
            "invoice_date": today - timedelta(days=30),
            "due_date": today - timedelta(days=5),
            "status": StudentInvoice.Status.OVERDUE,
            "invoice_no": f"INV-SEED-OVERDUE-{class_students[1].student_id}",
        },
    ]

    for data in invoice_data:
        StudentInvoice.objects.update_or_create(
            invoice_no=data["invoice_no"],
            defaults={
                "class_student": data["class_student"],
                "fee_type": dummy_fee,
                "fee_type_class": FeeTypeClass.objects.filter(
                    fee_type=dummy_fee,
                    class_obj=data["class_student"].class_obj,
                ).first(),
                "invoice_date": data["invoice_date"],
                "due_date": data["due_date"],
                "status": data["status"],
                "subtotal": dummy_fee.amount,
                "tax_amount": Decimal("0.00"),
                "total_discount": Decimal("0.00"),
                "total_amount": dummy_fee.amount,
                "currency": dummy_fee.currency,
                "amount_paid": Decimal("0.00"),
                "remark": "Seed invoice for payment flow testing.",
            },
        )
