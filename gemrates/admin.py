from django.contrib import admin

from gemrates.models import ExchangeRate


@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = (
        "quotation_date",
        "from_currency",
        "to_currency",
        "source",
        "series",
        "conversion_rate",
        "inverse_rate",
    )
    list_display_links = ("quotation_date",)
    list_filter = (
        ("from_currency", admin.AllValuesFieldListFilter),
        ("to_currency", admin.AllValuesFieldListFilter),
        "source",
        "series",
    )
    search_fields = ("from_currency", "to_currency", "source", "series")
    search_help_text = "Search currency codes, source, or series."
    date_hierarchy = "date"
    ordering = ("-date", "from_currency", "to_currency", "source", "series")
    list_per_page = 50
    show_full_result_count = False
    readonly_fields = (
        "midpoint",
        "conversion_rate",
        "inverse_rate",
        "updated_at",
    )
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "date",
                    ("from_currency", "to_currency"),
                    ("source", "series"),
                )
            },
        ),
        (
            "Rates",
            {
                "description": (
                    "Stored quotes convert 1 unit of 'from currency' "
                    "into 'to currency'. The reference rate takes precedence "
                    "over the midpoint of buying and selling quotes. "
                    "The inverse shows the opposite direction, rounded to "
                    "3 decimal places."
                ),
                "fields": (
                    "reference",
                    ("buy", "sell"),
                    "midpoint",
                    ("conversion_rate", "inverse_rate"),
                ),
            },
        ),
        ("Last updated", {"fields": ("updated_at",)}),
    )

    @admin.display(description="Date", ordering="date")
    def quotation_date(self, obj):
        return obj.date.isoformat()

    @admin.display(description="RATE")
    def conversion_rate(self, obj):
        return f"{obj.rate:.3f}" if obj.rate else None

    @admin.display(description="INVERSE RATE")
    def inverse_rate(self, obj):
        return f"{1 / obj.rate:.3f}" if obj.rate else None
