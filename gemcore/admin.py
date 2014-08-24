from django.contrib import admin

from gemcore.models import Account, Book, Currency, Expense


class AccountAdmin(admin.ModelAdmin):

     prepopulated_fields = {'slug': ('name', 'currency')}


class BookAdmin(admin.ModelAdmin):

     prepopulated_fields = {'slug': ('name',)}


admin.site.register(Account, AccountAdmin)
admin.site.register(Book, BookAdmin)
admin.site.register(Currency)
admin.site.register(Expense)
