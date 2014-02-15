from django.contrib import admin

from gemcore.models import Book, Currency, Expense


admin.site.register(Book)
admin.site.register(Currency)
admin.site.register(Expense)
