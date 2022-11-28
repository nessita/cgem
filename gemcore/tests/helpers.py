# -*- coding: utf-8 -*-

import os
from collections import defaultdict

from django.contrib import messages
from django.contrib.messages import constants as message_constants
from django.test import TestCase, override_settings

from gemcore.tests.factory import Factory


@override_settings(SECURE_SSL_REDIRECT=False)
class BaseTestCase(TestCase):

    factory = Factory()
    maxDiff = None

    def data_file(self, filename):
        return os.path.join(os.path.dirname(__file__), 'data', filename)

    def assert_messages(self, request_or_response, **kwargs):
        tags = sorted(messages.DEFAULT_TAGS.values())
        assert set(kwargs).intersection(
            set(tags)
        ), 'At least one of "%s" has to be given as kwargs' % ', '.join(tags)
        msgs = defaultdict(list)
        # Attempt to retrieve messages from a request object
        try:
            # Do not use `getattr` so `.context` is lazy.
            user_messages = request_or_response._messages
        except AttributeError:
            user_messages = request_or_response.context['messages']
        for m in user_messages:
            level_tag = message_constants.DEFAULT_TAGS.get(m.level)
            msgs[level_tag].append(m.message)
        for kind, expected in kwargs.items():
            with self.subTest(kind=kind):
                actual = msgs.get(kind, [])
                self.assertCountEqual(actual, expected)

    def assert_no_messages(self, request_or_response):
        kwargs = {tag: [] for tag in messages.DEFAULT_TAGS.values()}
        self.assert_messages(request_or_response, **kwargs)
