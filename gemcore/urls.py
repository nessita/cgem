from django.conf.urls import patterns, url


urlpatterns = patterns(
    'gemcore.views',
    # books
    url(r'^$', 'books', name='books'),
    url(r'^add/$', 'book', name='add-book'),
    url(r'^(?P<book_slug>[\w-]+)/$', 'book', name='book'),
    url(r'^(?P<book_slug>[\w-]+)/fromfile/(?P<kind>expense|bank)/$',
        'load_from_file', name='load-from-file'),
    url(r'^(?P<book_slug>[\w-]+)/remove/$', 'book_remove', name='remove-book'),
    # entries
    url(r'^(?P<book_slug>[\w-]+)/entry/$', 'entries', name='entries'),
    url(r'^(?P<book_slug>[\w-]+)/entry/add/$', 'entry',
        name='add-entry'),
    url(r'^(?P<book_slug>[\w-]+)/entry/(?P<entry_id>\d+)/$', 'entry',
        name='entry'),
    url(r'^(?P<book_slug>[\w-]+)/entry/(?P<entry_id>\d+)/remove/$',
        'entry_remove', name='remove-entry'),
)
