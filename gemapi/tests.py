from decimal import Decimal

from django.conf import settings
from django.urls import reverse

from gemcore.models import Entry
from gemcore.tests.helpers import BaseTestCase


class AddEntryViewTestCase(BaseTestCase):
    url = reverse('api:entry-list')

    def make_auth_header(self, user=None):
        token = self.factory.make_token(user=user)
        return {'HTTP_AUTHORIZATION': 'Token ' + token.key}

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
        data = {
            'book': 'test-book',
            'account': 'test-account',
            'what': 'One Test',
            'amount': 555.56,
            'tags': [settings.ENTRY_DEFAULT_TAG],
            'country': 'US',
        }

        response = self.client.post(self.url, data=data, **auth)
        self.assertEqual(response.status_code, 201, response.content)

        entry = Entry.objects.get()
        self.assertEqual(entry.book.slug, 'test-book')
        self.assertEqual(entry.account.slug, 'test-account')
        self.assertEqual(entry.who.username, 'test-user')
        self.assertEqual(entry.what, 'One Test')
        self.assertEqual(entry.amount, Decimal('555.56'))
        self.assertEqual(entry.tags, [settings.ENTRY_DEFAULT_TAG])
        self.assertEqual(entry.country, 'US')
