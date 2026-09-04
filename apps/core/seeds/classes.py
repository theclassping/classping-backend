from apps.schools.models import Branch
from apps.academic_years.models import AcademicYear
from apps.staffs.models import Staff
from apps.students.models import Student
from apps.classes.models import Class, ClassTeacher, ClassStudent


def seed_classes():
    branch = Branch.objects.get(name="Main Campus")
    academic_year = AcademicYear.objects.get(
        branch=branch, 
        name="2026/2027"
    )
    
    teacher = Staff.objects.filter(
        staff_type=Staff.StaffType.TEACHER
    ).first()
    
    if not teacher:
        return

    classes_data = [
        {"name": "Class A"},
        {"name": "Class B"},
        {"name": "Class C"},
    ]

    for class_data in classes_data:
        class_obj, created = Class.objects.get_or_create(
            branch=branch,
            academic_year=academic_year,
            name=class_data["name"],
        )

        # Assign teacher to class
        ClassTeacher.objects.get_or_create(
            class_obj=class_obj,
            staff=teacher,
        )

    # Assign students to classes
    students = Student.objects.all()[:2]
    classes = Class.objects.filter(
        branch=branch,
        academic_year=academic_year
    )

    # Distribute students across classes
    if students and classes:
        # Assign Ethan to Class A and Class B
        if len(classes) > 0:
            ClassStudent.objects.get_or_create(
                class_obj=classes[0],
                student=students[0],
            )
        if len(classes) > 1:
            ClassStudent.objects.get_or_create(
                class_obj=classes[1],
                student=students[0],
            )
        
        # Assign Emma to Class B and Class C
        if len(classes) > 1:
            ClassStudent.objects.get_or_create(
                class_obj=classes[1],
                student=students[1],
            )
        if len(classes) > 2:
            ClassStudent.objects.get_or_create(
                class_obj=classes[2],
                student=students[1],
            )
