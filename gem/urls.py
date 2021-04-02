from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import include, path

import gemcore.views


admin.autodiscover()
urlpatterns = [
    path('', gemcore.views.home, name='home'),
    path('login/', LoginView.as_view(template_name='login.html'),
         name='login'),
    path('logout/', LogoutView.as_view(next_page='/'), name='logout'),
    path('api/', include('gemapi.urls')),
    path('book/', include('gemcore.urls')),
    path('admin/', admin.site.urls),
]
