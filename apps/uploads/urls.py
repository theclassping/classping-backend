"""
URL configuration for uploads API.
"""
from django.urls import path

from apps.uploads.views import PresignUrlView, UploadView

app_name = 'uploads'

urlpatterns = [
    path('presign/', PresignUrlView.as_view(), name='presign-url'),
    path('upload/<path:file_key>', UploadView.as_view(), name='upload-file'),
]
