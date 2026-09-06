from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Location


User = get_user_model()


class LocationApiTests(APITestCase):
	def setUp(self):
		self.user = User.objects.create_user(
			email="location-user@example.com",
			password="SecurePass123",
		)
		self.client.force_authenticate(self.user)

		self.country = Location.objects.create(
			name="Indonesia",
			code="ID",
			location_type="COUNTRY",
		)
		self.province = Location.objects.create(
			name="Jawa Barat",
			code="32",
			location_type="PROVINCE",
			parent=self.country,
		)
		Location.objects.create(
			name="Jawa Tengah",
			code="33",
			location_type="PROVINCE",
			parent=self.country,
		)

	def test_lists_locations_for_parent(self):
		response = self.client.get(
			"/api/locations/",
			{"parent_id": self.country.id},
		)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(len(response.data), 2)

	def test_filters_root_locations_with_null_parent(self):
		response = self.client.get(
			"/api/locations/",
			{"parent_id": "null"},
		)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual([item["id"] for item in response.data], [self.country.id])

	def test_filters_by_type_and_search(self):
		response = self.client.get(
			"/api/locations/",
			{"type": "province", "search": "barat"},
		)

		self.assertEqual(response.status_code, status.HTTP_200_OK)
		self.assertEqual(response.data[0]["name"], "Jawa Barat")
