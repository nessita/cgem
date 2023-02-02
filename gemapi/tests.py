import random
from decimal import Decimal

from django.conf import settings
from django.urls import reverse

from gemcore.constants import TAGS, ChoicesMixin
from gemcore.models import Entry
from gemcore.tests.helpers import BaseTestCase


class AddEntryViewTestCase(BaseTestCase):
    url = reverse('api:entry-list')

    def make_auth_header(self, user=None):
        token = self.factory.make_token(user=user)
        return {'HTTP_AUTHORIZATION': 'Token ' + token.key}

    def make_entry_data(self, book_slug=None, account_slug=None, **kwargs):
        if book_slug is None:
            book_slug = self.factory.make_book().slug
        if account_slug is None:
            account_slug = self.factory.make_account().slug
        data = {
            'book': book_slug,
            'account': account_slug,
            'what': 'One Test',
            'amount': '555.56',
            'tags': [settings.ENTRY_DEFAULT_TAG],
            'country': 'US',
        }
        data.update(kwargs)
        return data

    def test_authentication_required(self):
        for method in ('GET', 'OPTIONS', 'PATCH', 'POST', 'PUT', 'DELETE'):
            with self.subTest(method=method):
                response = getattr(self.client, method.lower())(self.url)
                self.assertEqual(response.status_code, 401)

    def test_method_not_allowed(self):
        auth = self.make_auth_header()
        for method in ('GET', 'PATCH', 'PUT', 'DELETE'):
            with self.subTest(method=method):
                response = getattr(self.client, method.lower())(
                    self.url, **auth
                )
                self.assertEqual(response.status_code, 405)

    def test_success(self):
        self.factory.make_book(slug='test-book')
        self.factory.make_account(slug='test-account')
        user = self.factory.make_user(username='test-user')
        auth = self.make_auth_header(user=user)
        data = self.make_entry_data()

        response = self.client.post(self.url, data=data, **auth)
        self.assertEqual(response.status_code, 201, response.content)

        entry = Entry.objects.get()
        self.assertEqual(entry.book.slug, data['book'])
        self.assertEqual(entry.account.slug, data['account'])
        self.assertEqual(entry.who, user)
        self.assertEqual(entry.what, data['what'])
        self.assertEqual(entry.amount, Decimal(data['amount']))
        self.assertEqual(entry.tags, data['tags'])
        self.assertEqual(entry.country, data['country'])

    def test_tags_default_value_if_tags_none(self):
        user = self.factory.make_user()
        auth = self.make_auth_header(user=user)
        data = self.make_entry_data(tags=[])

        response = self.client.post(self.url, data=data, **auth)
        self.assertEqual(response.status_code, 201, response.content)

        entry = Entry.objects.get()
        self.assertEqual(entry.tags, [settings.ENTRY_DEFAULT_TAG])

    def test_tags_default_value_if_tags_missing(self):
        user = self.factory.make_user()
        auth = self.make_auth_header(user=user)
        data = self.make_entry_data()
        data.pop('tags')

        response = self.client.post(self.url, data=data, **auth)
        self.assertEqual(response.status_code, 201, response.content)

        entry = Entry.objects.get()
        self.assertEqual(entry.tags, [settings.ENTRY_DEFAULT_TAG])

    def test_tags_by_code(self):
        user = self.factory.make_user()
        auth = self.make_auth_header(user=user)
        tags = random.choices(TAGS, k=3)
        data = self.make_entry_data(tags=tags)

        response = self.client.post(self.url, data=data, **auth)
        self.assertEqual(response.status_code, 201, response.content)

        entry = Entry.objects.get()
        self.assertCountEqual(entry.tags, tags)

    def test_tags_by_name(self):
        user = self.factory.make_user()
        auth = self.make_auth_header(user=user)
        (t1, l1), (t2, l2), (t3, l3), (t4, l4) = random.choices(
            ChoicesMixin.TAG_CHOICES, k=4
        )
        data = self.make_entry_data(
            tags=[l1.lower(), l2.capitalize(), l3, l4.upper()]
        )

        response = self.client.post(self.url, data=data, **auth)
        self.assertEqual(response.status_code, 201, response.content)

        entry = Entry.objects.get()
        self.assertCountEqual(entry.tags, [t1, t2, t3, t4])
