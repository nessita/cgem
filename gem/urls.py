from django.conf.urls import patterns, include, url
from django.contrib import admin

import gemcore.views


admin.autodiscover()
urlpatterns = [
    url(r'^$', gemcore.views.home),
    url(r'^book/', include('gemcore.urls')),
    url(r'^accounts/', include('allauth.urls')),
    url(r'^admin/', include(admin.site.urls)),
]
