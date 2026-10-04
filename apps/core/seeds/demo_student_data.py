from datetime import date, timedelta
from decimal import Decimal

from apps.activities.models import Activity, ActivityImage, ActivityStudent
from apps.classes.models import Class, ClassStudent, ClassTeacher
from apps.fee_types.models import FeeType, FeeTypeClass
from apps.student_invoices.models import StudentInvoice
from apps.students.models import Student


def seed_demo_student_data():
    students = list(Student.objects.filter(id__in=[5, 6, 7]).order_by("id"))
    class_obj = Class.objects.order_by("id").first()
    fee_type = FeeType.objects.order_by("id").first()

    if not students:
        return {"activities": 0, "invoices": 0, "missing_students": [5, 6, 7]}
    if not class_obj or not fee_type:
        return {"activities": 0, "invoices": 0, "missing_students": [], "error": "Run the normal seed first."}

    class_teacher = ClassTeacher.objects.filter(class_obj=class_obj).first()
    if not class_teacher:
        return {"activities": 0, "invoices": 0, "missing_students": [], "error": "No class teacher found."}

    class_students = {
        student.id: ClassStudent.objects.get_or_create(
            class_obj=class_obj,
            student=student,
            defaults={"is_current": True},
        )[0]
        for student in students
    }

    today = date.today()
    activity_count = 0
    invoice_count = 0

    for index in range(1, 6):
        activity, _ = Activity.objects.update_or_create(
            name=f"Demo Activity {index}",
            class_obj=class_obj,
            defaults={
                "class_teacher": class_teacher,
                "description": f"Demo activity data for students 5, 6, and 7 ({index}).",
                "activity_date": today - timedelta(days=index),
                "is_publish": True,
            },
        )
        for position, student in enumerate(students):
            ActivityStudent.objects.update_or_create(
                activity=activity,
                student=student,
                defaults={"position": position},
            )
            ActivityImage.objects.update_or_create(
                activity=activity,
                student=student,
                position=0,
                defaults={
                    "image_data": {
                        "object_key": f"demo/activities/activity-{index}-student-{student.id}.jpg",
                        "filename": f"activity-{index}-student-{student.id}.jpg",
                        "content_type": "image/jpeg",
                    },
                    "caption": f"Demo image for activity {index}.",
                },
            )
        activity_count += 1

    fee_type_class = FeeTypeClass.objects.filter(
        fee_type=fee_type,
        class_obj=class_obj,
    ).first()

    for index, student in enumerate(students):
        class_student = class_students[student.id]
        invoice_date = today - timedelta(days=index)
        StudentInvoice.objects.update_or_create(
            invoice_no=f"INV-DEMO-STUDENT-{student.id}",
            defaults={
                "class_student": class_student,
                "fee_type": fee_type,
                "fee_type_class": fee_type_class,
                "invoice_date": invoice_date,
                "due_date": invoice_date + timedelta(days=14),
                "status": StudentInvoice.Status.UNPAID,
                "subtotal": fee_type.amount,
                "tax_amount": Decimal("0.00"),
                "total_discount": Decimal("0.00"),
                "total_amount": fee_type.amount,
                "currency": fee_type.currency,
                "amount_paid": Decimal("0.00"),
                "remark": "Demo invoice data for API testing.",
            },
        )
        invoice_count += 1

    return {
        "activities": activity_count,
        "invoices": invoice_count,
        "missing_students": sorted(set([5, 6, 7]) - {student.id for student in students}),
    }
