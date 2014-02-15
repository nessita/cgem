from django.conf.urls import patterns, url


urlpatterns = patterns(
    'gemcore.views',
    url(r'^$', 'home', name='home'),
)
