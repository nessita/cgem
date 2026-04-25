from decimal import Decimal, InvalidOperation

from django import template
from django.conf import settings

register = template.Library()


@register.simple_tag
def planning_enabled():
    return settings.ENTRY_TAGS.get("planning") is not None


@register.filter
def money(value, symbol="$"):
    if value in (None, ""):
        return ""

    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value

    return f"{symbol}{amount:,.2f}"
