from django.conf.urls import patterns, url


urlpatterns = patterns(
    'gemcore.views',
    url(r'^$', 'home', name='home'),
    url(r'^book/add/$', 'book', name='add-book'),
    url(r'^book/(?P<book_id>\d+)/$', 'book', name='edit-book'),
    url(r'^book/(?P<book_id>\d+)/add/$', 'expense', name='add-expense'),
    url(r'^book/(?P<book_id>\d+)/remove/$', 'book_remove', name='remove-book'),
)
