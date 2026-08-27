from django.db import models


class School(models.Model):
    name = models.CharField(max_length=255)
    register_number = models.CharField(max_length=50, unique=True)
    image_data = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "schools"

    def __str__(self):
        return self.name
    
class Branch(models.Model):
    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name="branches",
    )

    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)
    location_id = models.IntegerField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "school_branches"
        constraints = [
            models.UniqueConstraint(
                fields=["school", "code"],
                name="unique_branch_code_per_school",
            )
        ]

    def __str__(self):
        return f"{self.school.name} - {self.name}"