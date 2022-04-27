from rest_framework import routers

import gemapi.views

router = routers.DefaultRouter()
router.register(r'entries', gemapi.views.AddEntryView)

urlpatterns = router.urls
