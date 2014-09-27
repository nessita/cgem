from django.contrib import admin

from gemcore.models import Account, Book, Entry


class AccountAdmin(admin.ModelAdmin):

    prepopulated_fields = {'slug': ('name',)}


class BookAdmin(admin.ModelAdmin):

    prepopulated_fields = {'slug': ('name',)}


class EntryAdmin(admin.ModelAdmin):

    search_fields = ('what', 'when')
    list_filter = ('who', 'account', 'when')


admin.site.register(Account, AccountAdmin)
admin.site.register(Book, BookAdmin)
admin.site.register(Entry, EntryAdmin)
