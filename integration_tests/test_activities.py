from django.utils import timezone

from .base import GUARDIAN_EMAIL, IntegrationTestCase


def activity_image(name, student=None):
    return {
        "student_id": student["id"] if student else None,
        "image_data": {
            "id": f"activities/{name}.jpg",
            "object_key": f"activities/{name}.jpg",
            "filename": f"{name}.jpg",
            "content_type": "image/jpeg",
        },
        "caption": name,
    }


class ActivityFlowTests(IntegrationTestCase):
    def create_activity(self, school, name, student_ids, images, is_publish=True):
        return self.post(school["teacher_client"], "/api/activities/", {
            "class_teacher_id": school["class_teacher_id"],
            "class_id": school["class_id"],
            "name": name,
            "description": f"{name} with Grade 1A",
            "activity_date": str(timezone.localdate()),
            "is_publish": is_publish,
            "student_ids": student_ids,
            "activity_images": images,
        })

    def guardian_view(self, email):
        client, _ = self.login(email)
        response = client.get("/api/activities/")
        self.assert_status(response, 200)
        return client, {
            row["name"]: {
                "students": [student["id"] for student in row["activity_students"]],
                "images": [img["caption"] for img in row["activity_images"]],
            }
            for row in response.data
        }

    def test_activity_photos_tagged_to_students(self):
        school = self.create_new_school()
        staff_client = school["staff_client"]
        teacher_client = school["teacher_client"]
        class_id = school["class_id"]
        ayu = school["student"]
        bima = self.create_student(staff_client, class_id, "Bima", "Saputra", "bima.parent@example.com")
        citra = self.create_student(staff_client, class_id, "Citra", "Wulan", "citra.parent@example.com")

        # "Select all" sends every student on the class roster.
        roster = teacher_client.get(f"/api/classes/{class_id}/students/")
        self.assert_status(roster, 200)
        all_student_ids = [row["student_id"] for row in roster.data]
        self.assertCountEqual(all_student_ids, [ayu["id"], bima["id"], citra["id"]])

        # Whole class, several photos: two of Ayu, one of Bima, one group photo.
        painting = self.create_activity(school, "Painting Day", all_student_ids, [
            activity_image("ayu-easel", ayu),
            activity_image("ayu-palette", ayu),
            activity_image("bima-brush", bima),
            activity_image("group-photo"),
        ])
        self.assertCountEqual(
            [row["id"] for row in painting["activity_students"]], all_student_ids,
        )
        self.assertEqual(
            [(row["caption"], row["student_id"]) for row in painting["activity_images"]],
            [
                ("ayu-easel", ayu["id"]),
                ("ayu-palette", ayu["id"]),
                ("bima-brush", bima["id"]),
                ("group-photo", None),
            ],
        )

        # Only some children joined, and only Bima is photographed.
        swimming = self.create_activity(
            school, "Swimming Practice", [ayu["id"], bima["id"]], [activity_image("bima-pool", bima)],
        )
        self.assertCountEqual(
            [row["id"] for row in swimming["activity_students"]], [ayu["id"], bima["id"]],
        )

        # A draft stays hidden from guardians even when their child is tagged.
        self.create_activity(
            school, "Draft Outing", [ayu["id"]], [activity_image("ayu-draft", ayu)], is_publish=False,
        )

        # The teacher tags the group photo to Citra afterwards.
        group_photo_id = painting["activity_images"][3]["id"]
        tagged = teacher_client.patch(
            f"/api/activity-images/{group_photo_id}/",
            {"student_id": citra["id"]},
            format="json",
        )
        self.assert_status(tagged, 200)
        self.assertEqual(tagged.data["student_id"], citra["id"])

        # Each guardian sees published activities their child joined, and only
        # the photos tagged to their own child.
        ayu_client, ayu_view = self.guardian_view(GUARDIAN_EMAIL)
        self.assertEqual(ayu_view, {
            "Painting Day": {"students": [ayu["id"]], "images": ["ayu-easel", "ayu-palette"]},
            "Swimming Practice": {"students": [ayu["id"]], "images": []},
        })

        _, bima_view = self.guardian_view("bima.parent@example.com")
        self.assertEqual(bima_view, {
            "Painting Day": {"students": [bima["id"]], "images": ["bima-brush"]},
            "Swimming Practice": {"students": [bima["id"]], "images": ["bima-pool"]},
        })

        citra_client, citra_view = self.guardian_view("citra.parent@example.com")
        self.assertEqual(citra_view, {
            "Painting Day": {"students": [citra["id"]], "images": ["group-photo"]},
        })

        # The image endpoint applies the same tagging rule.
        ayu_images = ayu_client.get("/api/activity-images/")
        self.assert_status(ayu_images, 200)
        self.assertEqual(
            sorted(row["caption"] for row in ayu_images.data), ["ayu-easel", "ayu-palette"],
        )
        hidden = citra_client.get(f"/api/activities/{swimming['id']}/")
        self.assert_status(hidden, 404)
