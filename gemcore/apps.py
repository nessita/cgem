from django.apps import AppConfig
from django.conf import settings
from django.core.checks import register


class GemcoreConfig(AppConfig):
    name = "gemcore"

    def ready(self):
        from gemcore.checks import check_entry_tags

        register(check_entry_tags)

        if settings.DEBUG:
            from gemcore import assets

            assets.connect()
