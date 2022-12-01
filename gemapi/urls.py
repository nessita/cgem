from django.urls import path
from rest_framework import routers

import gemapi.views

router = routers.DefaultRouter()
router.register(r'entries', gemapi.views.AddEntryView)

urlpatterns = [
    path('version', gemapi.views.VersionView.as_view(), name='version')
] + router.urls
