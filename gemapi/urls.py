from django.urls import include, path
from rest_framework import routers

from gemapi import views


router = routers.DefaultRouter()
router.register(r'entries', views.EntryViewSet, basename='Entries')


urlpatterns = [
    path('transactions', views.transactions, name='transactions'),
    path('report', views.report, name='report'),
    path('', include(router.urls)),
]
