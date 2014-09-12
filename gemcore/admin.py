from django.contrib import admin

from gemcore.models import Account, Book, Currency, Entry


class AccountAdmin(admin.ModelAdmin):

    prepopulated_fields = {'slug': ('name', 'currency')}


class BookAdmin(admin.ModelAdmin):

    prepopulated_fields = {'slug': ('name',)}


class EntryAdmin(admin.ModelAdmin):

    search_fields = ('what', 'when')
    list_filter = ('who', 'account', 'when')


admin.site.register(Account, AccountAdmin)
admin.site.register(Book, BookAdmin)
admin.site.register(Currency)
admin.site.register(Entry, EntryAdmin)
