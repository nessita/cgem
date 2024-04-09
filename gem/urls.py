from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import include, path

import gemapi.urls
import gemcore.views

login_view = LoginView.as_view(
    template_name='login.html', redirect_authenticated_user=True)


admin.autodiscover()
urlpatterns = [
    path('', gemcore.views.home, name='home'),
    path('login/', login_view, name='login'),
    path('logout/', LogoutView.as_view(next_page='/'), name='logout'),
    path('book/', include('gemcore.urls')),
    path('admin/', admin.site.urls),
    path('status/', include('health_check.urls')),
    path('api/', include((gemapi.urls, 'api'))),
]
