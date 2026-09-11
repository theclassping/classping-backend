"""
URL configuration for uploads API.
"""
from django.urls import path

from apps.uploads.views import MediaDownloadUrlView, PresignUrlView, UploadView

app_name = 'uploads'

urlpatterns = [
    path('presign/', PresignUrlView.as_view(), name='presign-url'),
    path('upload/<path:file_key>', UploadView.as_view(), name='upload-file'),
    path('download/url/',
            MediaDownloadUrlView.as_view(),
            name="download-url",
        ),
]
