from django.conf import settings
from django.utils.functional import lazy
from django_countries import countries

from gemrates.constants import CURRENCY_CHOICES


def get_tag_choices():
    config = settings.ENTRY_TAGS
    choices = config.get("choices", []) if isinstance(config, dict) else []
    if not isinstance(choices, (list, tuple)):
        return []
    return choices


TAGS = lazy(lambda: [code for code, label in get_tag_choices()], list)()


class ChoicesMixin:
    ASSET_CHOICES = settings.ASSET_CATEGORIES
    TAG_CHOICES = lazy(get_tag_choices, list)()
    CURRENCY_CHOICES = CURRENCY_CHOICES
    COUNTRY_CHOICES = countries
