from django.urls import path
from rest_framework import routers

import gemapi.views

router = routers.DefaultRouter()
router.register(r"entries", gemapi.views.EntriesView)

urlpatterns = [
    path(
        "<slug:book_slug>/entries/",
        gemapi.views.EntriesView.as_view({"get": "list", "post": "create"}),
        name="book-entry-list",
    ),
    path("version", gemapi.views.VersionView.as_view(), name="version"),
] + router.urls
