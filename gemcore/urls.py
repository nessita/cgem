from django.conf.urls import patterns, url


urlpatterns = patterns(
    'gemcore.views',
    url(r'^$', 'books', name='books'),
    url(r'^add/$', 'book', name='add-book'),
    url(r'^(?P<book_slug>[\w-]+)/$', 'book', name='edit-book'),
    url(r'^(?P<book_slug>[\w-]+)/add/$', 'expense', name='add-expense'),
    url(r'^(?P<book_slug>[\w-]+)/remove/$', 'book_remove', name='remove-book'),

    url(r'^(?P<book_slug>[\w-]+)/expense/$', 'expenses', name='expenses'),
    url(r'^(?P<book_slug>[\w-]+)/expense/add/$', 'expense', name='add-expense'),
    url(r'^(?P<book_slug>[\w-]+)/expense/(?P<expense_id>\d+)/$', 'expense',
        name='edit-expense'),
    url(r'^(?P<book_slug>[\w-]+)/expense/(?P<expense_id>\d+)/remove/$',
        'expense_remove', name='remove-expense'),

    url(r'^(?P<book_slug>\w+)/expense/(?P<tag_slug>\w+)/$', 'expenses',
        name='expenses-by-tag'),
)
