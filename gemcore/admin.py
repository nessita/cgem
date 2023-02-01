from django.contrib import admin

from gemcore.models import (
    Account,
    Book,
    Entry,
    EntryHistory,
    ParserConfig,
    TagRegex,
)


class TagRegexInline(admin.StackedInline):
    model = TagRegex
    extra = 1
    fk_name = 'account'


class AccountAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'slug',
        'currency',
        'active',
        'people',
        'parser_config',
    )
    prepopulated_fields = {'slug': ('name',)}
    inlines = (TagRegexInline,)

    def people(self, instance):
        return ', '.join(u.username for u in instance.users.all())


class BookAdmin(admin.ModelAdmin):
    prepopulated_fields = {'slug': ('name',)}


class TagListFilter(admin.SimpleListFilter):
    """List filter based on the values from a model's ArrayField."""

    title = 'Tags'
    parameter_name = 'tag'

    def lookups(self, request, model_admin):
        tags = Entry.objects.values_list('tags', flat=True)
        return sorted({(tag, tag) for item in tags for tag in item if tag})

    def queryset(self, request, queryset):
        lookup_value = self.value()
        if lookup_value:
            queryset = queryset.filter(tags__contains=[lookup_value])
        return queryset


class EntryAdmin(admin.ModelAdmin):
    search_fields = ('what', 'when')
    list_filter = ('who', 'account', 'when', TagListFilter)


class EntryHistoryAdmin(admin.ModelAdmin):
    pass


class ParserConfigAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'date_format',
        'separators',
        'when',
        'what',
        'amount',
        'notes',
        'ignore_rows',
        'country',
    )

    def separators(self, instance):
        return '100%s000%s00' % (
            instance.decimal_point,
            instance.thousands_sep,
        )


class TagRegexAdmin(admin.ModelAdmin):
    list_display = ('regex', 'tag', 'account')


admin.site.register(Account, AccountAdmin)
admin.site.register(Book, BookAdmin)
admin.site.register(Entry, EntryAdmin)
admin.site.register(EntryHistory, EntryHistoryAdmin)
admin.site.register(ParserConfig, ParserConfigAdmin)
admin.site.register(TagRegex, TagRegexAdmin)
