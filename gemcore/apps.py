from django.apps import AppConfig
from django.conf import settings


class GemcoreConfig(AppConfig):
    name = "gemcore"

    def ready(self):
        if settings.DEBUG:
            from gemcore import assets

            assets.connect()
