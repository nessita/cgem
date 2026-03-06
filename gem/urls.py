from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import include, path
from health_check.views import HealthCheckView

import gemapi.urls
import gemcore.views

login_view = LoginView.as_view(
    template_name='login.html', redirect_authenticated_user=True)


admin.autodiscover()
urlpatterns = [
    path('', gemcore.views.home, name='home'),
    path('api/', include((gemapi.urls, 'api'))),
    path('login/', login_view, name='login'),
    path('logout/', LogoutView.as_view(next_page='/'), name='logout'),
    path('book/', include('gemcore.urls')),
    path('admin/', admin.site.urls),
    path(
        "status/",
        HealthCheckView.as_view(
            checks=[
                "health_check.Cache",
                "health_check.Database",
                "health_check.Mail",
                "health_check.Storage",
            ]
        ),
    ),
]
