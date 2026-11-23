from decimal import Decimal, InvalidOperation

from django import template
from django.conf import settings
from django.urls import reverse

register = template.Library()


@register.simple_tag
def planning_enabled():
    return settings.ENTRY_TAGS.get("planning") is not None


@register.simple_tag(takes_context=True)
def book_navigation(context, book):
    request = context["request"]
    match = request.resolver_match
    page = match.url_name if match else None
    active = {
        "entry": "entries",
        "remove-entry": "entries",
        "merge-entry": "entries",
        "planning-year": "planning",
    }.get(page, page)
    params = request.GET.copy()
    if match:
        for name, parameter in (
            ("account_slug", "account"),
            ("currency", "currency"),
        ):
            if match.kwargs.get(name):
                params[parameter] = match.kwargs[name]
    query = "?" + params.urlencode() if params else ""
    pages = [
        ("entries", "Entries"),
        ("add-entry", "New entry"),
        ("account-transfer", "Account transfer"),
        ("balance", "Balances"),
    ]
    if planning_enabled():
        pages.append(("planning", "Planning"))
    pages.append(("load-from-file", "Load file"))
    return [
        {
            "label": label,
            "href": reverse(name, args=[book.slug]) + query,
            "current": name == active,
        }
        for name, label in pages
    ]


@register.filter
def money(value, symbol="$"):
    if value in (None, ""):
        return ""

    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value

    return f"{symbol}{amount:,.2f}"
