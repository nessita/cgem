from django.conf.urls import patterns, url

import gemcore.views


urlpatterns = [
    # books
    url(r'^$', gemcore.views.books, name='books'),
    url(r'^add/$', gemcore.views.book, name='add-book'),
    url(r'^(?P<book_slug>[\w-]+)/$', gemcore.views.book, name='book'),
    url(r'^(?P<book_slug>[\w-]+)/fromfile/$', gemcore.views.load_from_file,
        name='load-from-file'),
    url(r'^(?P<book_slug>[\w-]+)/transfer/$', gemcore.views.account_transfer,
        name='account-transfer'),
    url(r'^(?P<book_slug>[\w-]+)/remove/$', gemcore.views.book_remove,
        name='remove-book'),
    # entries
    url(r'^(?P<book_slug>[\w-]+)/entry/$',
        gemcore.views.entries, name='entries'),
    url(r'^(?P<book_slug>[\w-]+)/entry/add/$',
        gemcore.views.entry, name='add-entry'),
    url(r'^(?P<book_slug>[\w-]+)/entry/(?P<entry_id>\d+)/$',
        gemcore.views.entry, name='entry'),
    url(r'^(?P<book_slug>[\w-]+)/entry/(?P<entry_id>\d+)/remove/$',
        gemcore.views.entry_remove, name='remove-entry'),
    url(r'^(?P<book_slug>[\w-]+)/balance/$',
        gemcore.views.balance, name='balance'),
    url(r'^(?P<book_slug>[\w-]+)/balance/(?P<currency_code>[A-Z]{3})/$',
        gemcore.views.balance, name='balance'),
    url(r'^(?P<book_slug>[\w-]+)/balance/(?P<account_slug>[\w-]+)/$',
        gemcore.views.balance, name='balance'),
]
