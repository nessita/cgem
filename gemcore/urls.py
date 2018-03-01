from django.urls import path

import gemcore.views


urlpatterns = [
    # books
    path('', gemcore.views.books, name='books'),
    path('add/', gemcore.views.book, name='add-book'),
    path('<slug:book_slug>/', gemcore.views.book, name='book'),
    path('<slug:book_slug>/fromfile/', gemcore.views.load_from_file,
         name='load-from-file'),
    path('<slug:book_slug>/transfer/', gemcore.views.account_transfer,
         name='account-transfer'),
    # entries
    path('<slug:book_slug>/entry/',
         gemcore.views.entries, name='entries'),
    path('<slug:book_slug>/entry/add/',
         gemcore.views.entry, name='add-entry'),
    path('<slug:book_slug>/entry/<int:entry_id>/',
         gemcore.views.entry, name='entry'),
    path('<slug:book_slug>/entry/<int:entry_id>/remove/',
         gemcore.views.entry_remove, name='remove-entry'),
    path('<slug:book_slug>/entry/remove/',
         gemcore.views.entry_remove, name='remove-entry'),
    path('<slug:book_slug>/entry/merge/',
         gemcore.views.entry_merge, name='merge-entry'),
    path('<slug:book_slug>/balance/',
         gemcore.views.balance, name='balance'),
    path('<slug:book_slug>/balance/<slug:account_slug>/',
         gemcore.views.balance, name='balance'),
    path('<slug:book_slug>/balance/currency/<str:currency>/',
         gemcore.views.balance, name='balance'),
]
