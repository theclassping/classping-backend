from django.urls import path

from .views import ParentContextView

urlpatterns = [
    path("context/", ParentContextView.as_view(), name="parent-context"),
]
