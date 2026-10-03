from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.forms import BaseInlineFormSet, inlineformset_factory

from apps.academic_years.models import AcademicYear
from apps.activities.models import Activity, ActivityImage, ActivityStudent
from apps.classes.models import Class, ClassTeacher
from apps.fee_types.models import FeeType, FeeTypeClass
from apps.guardians.models import Guardian
from apps.locations.models import Location
from apps.payments.models import Payment, PaymentProof
from apps.schools.models import Branch, School
from apps.score_settings.models import ScoreSetting
from apps.student_invoices.models import StudentInvoice
from apps.students.models import Student, StudentGuardian
from apps.staffs.models import Staff
from apps.users.models import User


class HierarchicalClassChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.branch.school.name} - {obj.branch.name} - {obj.name}"


class HierarchicalClassMultipleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.branch.school.name} - {obj.branch.name} - {obj.name}"


class SearchableImageUploadMixin:
    """Expose image_data as a real upload while retaining JSON model storage."""

    def _add_image_upload(self):
        if "image_data" in self.fields:
            # Media JSON is an internal storage field. Users must use the upload control.
            self.fields["image_data"].widget = forms.HiddenInput()
        self.fields["image_file"] = forms.ImageField(
            required=False,
            label="Image upload",
            help_text="Upload an image; it will be stored using the API media metadata format.",
        )
        self.fields["image_file"].widget.attrs["accept"] = "image/*"


class ActivityForm(forms.ModelForm):
    class_obj = HierarchicalClassChoiceField(queryset=Class.objects.none())
    class Meta:
        model = Activity
        fields = [
            "name",
            "class_obj",
            "class_teacher",
            "activity_date",
            "description",
            "is_publish",
        ]
        widgets = {"activity_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["class_obj"].queryset = Class.objects.select_related(
            "branch", "academic_year"
        ).order_by("branch__name", "name")
        self.fields["class_teacher"].queryset = ClassTeacher.objects.select_related(
            "staff__user", "class_obj"
        ).order_by("class_obj__name", "staff__user__last_name")

    def clean(self):
        cleaned_data = super().clean()
        class_obj = cleaned_data.get("class_obj")
        class_teacher = cleaned_data.get("class_teacher")
        if class_obj and class_teacher and class_teacher.class_obj_id != class_obj.pk:
            self.add_error("class_teacher", "Choose a teacher assigned to this class.")
        return cleaned_data


class FeeTypeForm(forms.ModelForm):
    classes = HierarchicalClassMultipleChoiceField(
        queryset=Class.objects.none(),
        required=False,
        label="Applicable classes",
    )

    class Meta:
        model = FeeType
        fields = [
            "branch", "name", "description", "amount", "currency",
            "is_recurring", "recurring_frequency", "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = Branch.objects.select_related("school").order_by(
            "school__name", "name"
        )
        branch_id = self.data.get("branch") or getattr(self.instance, "branch_id", None)
        if branch_id:
            self.fields["classes"].queryset = Class.objects.filter(
                branch_id=branch_id
            ).select_related("academic_year").order_by("academic_year__name", "name")
        if self.instance.pk:
            self.fields["classes"].initial = Class.objects.filter(
                fee_type_classes__fee_type=self.instance
            )

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("is_recurring") and not cleaned_data.get("recurring_frequency"):
            self.add_error("recurring_frequency", "Select a billing frequency for recurring fees.")
        if not cleaned_data.get("is_recurring"):
            cleaned_data["recurring_frequency"] = None
        return cleaned_data


class AcademicYearForm(forms.ModelForm):
    class Meta:
        model = AcademicYear
        fields = ["branch", "name", "start_date", "end_date", "is_current"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = Branch.objects.select_related("school").order_by(
            "school__name", "name"
        )

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        if start_date and end_date and start_date >= end_date:
            self.add_error("end_date", "End date must be later than the start date.")
        return cleaned_data


class LocationForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ["name", "code", "location_type", "parent"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parent"].queryset = Location.objects.exclude(
            pk=self.instance.pk
        ).order_by("tree_id", "lft")

    def clean(self):
        cleaned_data = super().clean()
        parent = cleaned_data.get("parent")
        if (
            self.instance.pk
            and parent
            and self.instance.is_ancestor_of(parent, include_self=True)
        ):
            self.add_error("parent", "A location cannot be moved beneath itself or one of its descendants.")
        return cleaned_data


class ScoreSettingForm(forms.ModelForm):
    min_score = forms.DecimalField(max_digits=10, decimal_places=2, required=False)
    max_score = forms.DecimalField(max_digits=10, decimal_places=2, required=False)
    levels = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Enter one level name per line, ordered from lowest to highest.",
    )

    class Meta:
        model = ScoreSetting
        fields = ["branch", "name", "description", "score_type"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = Branch.objects.select_related("school").order_by(
            "school__name", "name"
        )
        if self.instance.pk:
            if self.instance.score_type == ScoreSetting.ScoreType.NUMERIC:
                numeric_score = getattr(self.instance, "numeric_score", None)
                if numeric_score:
                    self.fields["min_score"].initial = numeric_score.min_score
                    self.fields["max_score"].initial = numeric_score.max_score
            else:
                self.fields["levels"].initial = "\n".join(
                    self.instance.level_scores.order_by("position").values_list(
                        "name", flat=True
                    )
                )

    def clean(self):
        cleaned_data = super().clean()
        score_type = cleaned_data.get("score_type")
        if score_type == ScoreSetting.ScoreType.NUMERIC:
            minimum = cleaned_data.get("min_score")
            maximum = cleaned_data.get("max_score")
            if minimum is None:
                self.add_error("min_score", "Enter the minimum score.")
            if maximum is None:
                self.add_error("max_score", "Enter the maximum score.")
            if minimum is not None and maximum is not None and minimum > maximum:
                self.add_error("max_score", "Maximum score must be at least the minimum score.")
        elif score_type == ScoreSetting.ScoreType.LEVEL:
            names = [name.strip() for name in cleaned_data.get("levels", "").splitlines()]
            names = [name for name in names if name]
            if not names:
                self.add_error("levels", "Enter at least one score level.")
            elif len(names) != len(set(name.casefold() for name in names)):
                self.add_error("levels", "Score level names must be unique.")
            cleaned_data["level_names"] = names
        return cleaned_data


class PaymentRejectionForm(forms.Form):
    rejection_reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}),
        max_length=2000,
        label="Reason for rejection",
    )


class SchoolForm(SearchableImageUploadMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_image_upload()

    class Meta:
        model = School
        fields = ["name", "register_number", "image_data", "is_active"]


class ClassForm(forms.ModelForm):
    teachers = forms.ModelMultipleChoiceField(
        queryset=Staff.objects.none(),
        required=False,
    )
    students = forms.ModelMultipleChoiceField(
        queryset=Student.objects.none(),
        required=False,
    )
    current_students = forms.ModelMultipleChoiceField(
        queryset=Student.objects.none(),
        required=False,
        label="Current students",
    )

    class Meta:
        model = Class
        fields = ["name", "branch", "academic_year"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = Branch.objects.select_related("school").order_by(
            "school__name", "name"
        )
        self.fields["academic_year"].queryset = AcademicYear.objects.select_related(
            "branch__school"
        ).order_by("branch__school__name", "branch__name", "-start_date")
        self.fields["teachers"].queryset = Staff.objects.filter(
            staff_type=Staff.StaffType.TEACHER
        ).select_related("branch__school").order_by("first_name", "last_name")
        self.fields["students"].queryset = Student.objects.order_by("last_name", "first_name")
        self.fields["current_students"].queryset = self.fields["students"].queryset
        if self.instance.pk:
            self.fields["teachers"].initial = Staff.objects.filter(
                class_teaching_assignments__class_obj=self.instance
            )
            self.fields["students"].initial = Student.objects.filter(
                class_students__class_obj=self.instance
            )
            self.fields["current_students"].initial = Student.objects.filter(
                class_students__class_obj=self.instance,
                class_students__is_current=True,
            )

    def clean(self):
        cleaned_data = super().clean()
        branch = cleaned_data.get("branch")
        academic_year = cleaned_data.get("academic_year")
        if branch and academic_year and academic_year.branch_id != branch.pk:
            self.add_error("academic_year", "Choose an academic year from this branch.")
        teachers = cleaned_data.get("teachers")
        if branch and teachers and teachers.exclude(branch=branch).exists():
            self.add_error("teachers", "Teachers must belong to the selected branch.")
        students = cleaned_data.get("students")
        current_students = cleaned_data.get("current_students")
        if students is not None and current_students is not None:
            if not set(current_students).issubset(set(students)):
                self.add_error("current_students", "Current students must be assigned to this class.")
        return cleaned_data


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["student_invoice", "amount", "payment_method"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        invoices = StudentInvoice.objects.select_related(
            "class_student__student", "class_student__class_obj__branch__school"
        ).filter(status=StudentInvoice.Status.UNPAID, payment__isnull=True)
        if self.instance.pk:
            invoices = invoices | StudentInvoice.objects.filter(
                pk=self.instance.student_invoice_id
            )
        self.fields["student_invoice"].queryset = invoices.order_by("invoice_date", "pk")

    def clean(self):
        cleaned_data = super().clean()
        invoice = cleaned_data.get("student_invoice")
        if not self.instance.pk and invoice:
            if Payment.objects.filter(student_invoice=invoice).exists():
                self.add_error("student_invoice", "This invoice already has a payment record.")
        return cleaned_data


class StudentGuardianInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        active_forms = [
            form for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE")
            and form.cleaned_data.get("guardian")
        ]
        if not active_forms:
            raise ValidationError("At least one guardian must remain linked to the student.")
        if sum(bool(form.cleaned_data.get("is_primary")) for form in active_forms) != 1:
            raise ValidationError("Choose exactly one primary guardian.")


StudentGuardianFormSet = inlineformset_factory(
    Student,
    StudentGuardian,
    fields=["guardian", "relationship", "is_primary"],
    formset=StudentGuardianInlineFormSet,
    extra=1,
    can_delete=True,
)

class ActivityImageForm(SearchableImageUploadMixin, forms.ModelForm):
    image_data = forms.JSONField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = ActivityImage
        fields = ["student", "image_data", "caption", "position"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_image_upload()


class PaymentProofForm(SearchableImageUploadMixin, forms.ModelForm):
    image_data = forms.JSONField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = PaymentProof
        fields = ["image_data"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_image_upload()


ActivityImageFormSet = inlineformset_factory(
    Activity,
    ActivityImage,
    form=ActivityImageForm,
    extra=1,
    can_delete=True,
)

ActivityStudentFormSet = inlineformset_factory(
    Activity,
    ActivityStudent,
    fields=["student", "position"],
    extra=1,
    can_delete=True,
)

PaymentProofFormSet = inlineformset_factory(
    Payment,
    PaymentProof,
    form=PaymentProofForm,
    extra=1,
    can_delete=True,
)


class StudentForm(SearchableImageUploadMixin, forms.ModelForm):
    current_class = HierarchicalClassChoiceField(
        queryset=Class.objects.none(),
        required=False,
        label="Current class",
    )
    location = forms.ModelChoiceField(
        queryset=Location.objects.none(),
        required=False,
    )
    status = forms.ChoiceField(choices=Student.STATUS_CHOICES)

    class Meta:
        model = Student
        fields = [
            "first_name", "middle_name", "last_name", "nickname",
            "date_of_birth", "image_data", "gender", "address", "enroll_date", "status",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "enroll_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_image_upload()
        self.fields["current_class"].queryset = Class.objects.select_related(
            "branch__school", "academic_year"
        ).order_by("branch__school__name", "branch__name", "name")
        self.fields["location"].queryset = Location.objects.order_by("tree_id", "lft")
        if self.instance.pk:
            current_assignment = self.instance.class_students.filter(
                is_current=True
            ).first()
            if current_assignment:
                self.fields["current_class"].initial = current_assignment.class_obj_id
            if self.instance.location_id:
                self.fields["location"].initial = self.instance.location_id

    def save(self, commit=True):
        student = super().save(commit=False)
        student.location_id = (
            self.cleaned_data["location"].pk
            if self.cleaned_data.get("location")
            else None
        )
        if commit:
            student.save()
            self.save_m2m()
        return student


class GuardianForm(SearchableImageUploadMixin, forms.ModelForm):
    user = forms.ModelChoiceField(
        queryset=User.objects.none(),
        label="Parent user account",
        help_text="Create a Parent account in Users first if it is not listed.",
    )

    class Meta:
        model = Guardian
        fields = ["user", "name", "phone_number", "email", "image_data"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._add_image_upload()
        eligible_users = User.objects.filter(role=User.Role.PARENT)
        if self.instance.pk:
            eligible_users = eligible_users.filter(
                Q(guardian__isnull=True) | Q(pk=self.instance.user_id)
            )
        else:
            eligible_users = eligible_users.filter(guardian__isnull=True)
        self.fields["user"].queryset = eligible_users.order_by("email")
