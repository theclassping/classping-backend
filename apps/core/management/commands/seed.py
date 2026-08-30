from django.core.management.base import BaseCommand

from apps.core.seeds.locations import seed_locations
from apps.core.seeds.schools import seed_schools
from apps.core.seeds.branches import seed_branches
from apps.core.seeds.users import seed_users
from apps.core.seeds.staffs import seed_staffs
from apps.core.seeds.guardians import seed_guardians
from apps.core.seeds.students import seed_students
from apps.core.seeds.student_guardians import seed_student_guardians


class Command(BaseCommand):
    help = "Seed initial application data"

    def handle(self, *args, **options):
        self.stdout.write("Seeding locations...")
        seed_locations()

        self.stdout.write("Seeding schools...")
        seed_schools()

        self.stdout.write("Seeding branches...")
        seed_branches()

        self.stdout.write("Seeding users...")
        seed_users()

        self.stdout.write("Seeding staffs...")
        seed_staffs()

        self.stdout.write("Seeding guardians...")
        seed_guardians()

        self.stdout.write("Seeding students...")
        seed_students()

        self.stdout.write("Seeding student guardians...")
        seed_student_guardians()

        self.stdout.write(
            self.style.SUCCESS(
                "Database seeded successfully."
            )
        )