from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def money(value, symbol="$"):
    if value in (None, ""):
        return ""

    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value

    return f"{symbol}{amount:,.2f}"
