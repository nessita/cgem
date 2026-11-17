import logging
import os
from collections import defaultdict
from contextlib import contextmanager
from html.parser import HTMLParser
from types import SimpleNamespace

from django.contrib import messages
from django.contrib.messages import constants as message_constants
from django.db import DEFAULT_DB_ALIAS, connections
from django.template.response import SimpleTemplateResponse
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from gemcore.tests.factory import Factory


def _capture_operation_queries(execute, using):
    with CaptureQueriesContext(connections[using]) as queries:
        result = execute()
        if (
            isinstance(result, SimpleTemplateResponse)
            and not result.is_rendered
        ):
            result.render()
    return result, list(queries)


class ElementCollector(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


@override_settings(
    SECURE_SSL_REDIRECT=False,
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    },
)
class BaseTestCase(TestCase):
    factory = Factory()
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for name, level in (
            ("gemcore.parser", logging.WARNING),
            ("django.request", logging.ERROR),
        ):
            logger = logging.getLogger(name)
            cls.addClassCleanup(logger.setLevel, logger.level)
            logger.setLevel(level)

    def data_file(self, filename):

        return os.path.join(os.path.dirname(__file__), "data", filename)

    @contextmanager
    def assertQueryCountUnchanged(
        self, execute, make_more, *, using=DEFAULT_DB_ALIAS, query_filter=None
    ):
        """Growing input must not introduce hidden per-item queries.

        ``execute`` must evaluate lazy results. Template responses are rendered
        during capture. ``make_more`` runs outside capture; both results are
        available in the context body. An explicit ``query_filter`` can isolate
        constant lookups in operations whose writes grow with the input.
        """
        before, before_queries = _capture_operation_queries(execute, using)
        make_more()
        after, after_queries = _capture_operation_queries(execute, using)
        counted_before = [
            query
            for query in before_queries
            if query_filter is None or query_filter(query)
        ]
        counted_after = [
            query
            for query in after_queries
            if query_filter is None or query_filter(query)
        ]
        yield SimpleNamespace(
            before=before,
            after=after,
            before_queries=before_queries,
            after_queries=after_queries,
            before_count=len(counted_before),
            after_count=len(counted_after),
        )
        before_sql = "\n".join(query["sql"] for query in counted_before)
        after_sql = "\n".join(query["sql"] for query in counted_after)
        self.assertEqual(
            len(counted_before),
            len(counted_after),
            f"Query count changed from {len(counted_before)} "
            f"to {len(counted_after)}.\n"
            f"Before queries:\n{before_sql}\nAfter queries:\n{after_sql}",
        )

    def assert_messages(self, request_or_response, **kwargs):
        tags = sorted(messages.DEFAULT_TAGS.values())
        assert set(kwargs).intersection(
            set(tags)
        ), 'At least one of "%s" has to be given as kwargs' % ", ".join(tags)
        msgs = defaultdict(list)
        # Attempt to retrieve messages from a request object
        try:
            # Do not use `getattr` so `.context` is lazy.
            user_messages = request_or_response._messages
        except AttributeError:
            user_messages = request_or_response.context["messages"]
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
