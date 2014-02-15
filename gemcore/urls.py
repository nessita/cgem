from django.conf.urls import patterns, url


urlpatterns = patterns(
    'gemcore.views',
    url(r'^$', 'home', name='home'),
    url(r'^book/add/$', 'add_book', name='add-book'),
    url(r'^expense/add/$', 'add_expense', name='add-expense'),
)
