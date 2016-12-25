from django.conf.urls import include, url
from django.contrib import admin
from django.contrib.auth.views import login, logout

import gemcore.views


admin.autodiscover()
urlpatterns = [
    url(r'^$', gemcore.views.home, name='home'),
    url(r'^login/$', login, name='login',
        kwargs={'template_name': 'login.html'}),
    url(r'^logout/$', logout, name='logout', kwargs={'next_page': '/'}),
    url(r'^book/', include('gemcore.urls')),
    url(r'^admin/', include(admin.site.urls)),
]
