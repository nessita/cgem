from bitfield import BitField
from bitfield.admin import BitFieldListFilter
from bitfield.forms import BitFieldCheckboxSelectMultiple
from django.contrib import admin

from gemcore.models import Account, Book, Entry, EntryHistory, TagRegex


class TagRegexInline(admin.StackedInline):

    model = TagRegex
    extra = 1
    fk_name = 'account'


class AccountAdmin(admin.ModelAdmin):

    list_display = (
        'name', 'slug', 'currency_code', 'active',  'people', 'parser')
    prepopulated_fields = {'slug': ('name',)}
    inlines = (TagRegexInline,)

    def people(self, instance):
        return ', '.join(u.username for u in instance.users.all())


class BookAdmin(admin.ModelAdmin):

    prepopulated_fields = {'slug': ('name',)}


class EntryAdmin(admin.ModelAdmin):

    search_fields = ('what', 'when')
    list_filter = (
        'who', 'account', 'when',
        ('tags', BitFieldListFilter),
    )
    formfield_overrides = {
        BitField: {'widget': BitFieldCheckboxSelectMultiple},
    }


class EntryHistoryAdmin(admin.ModelAdmin):

    pass  # list_display = ('regex', 'tag', 'account')


class TagRegexAdmin(admin.ModelAdmin):

    list_display = ('regex', 'tag', 'account')


admin.site.register(Account, AccountAdmin)
admin.site.register(Book, BookAdmin)
admin.site.register(Entry, EntryAdmin)
admin.site.register(EntryHistory, EntryHistoryAdmin)
admin.site.register(TagRegex, TagRegexAdmin)
