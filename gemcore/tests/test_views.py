
from django.urls import reverse

from gemcore.tests.helpers import BaseTestCase


class BalanceViewTestCase(BaseTestCase):

    def test_get_by_account(self):
        user = self.factory.make_user()
        book = self.factory.make_book(users=[user])
        account = self.factory.make_account(users=[user])
        kwargs = {'book_slug': book.slug, 'account_slug': account.slug}
        url = reverse('balance', kwargs=kwargs)

        assert self.client.login(username=user.username, password='test')
        response = self.client.get(url)

        self.assertContains(response, 'Balances for %s' % book.name)

    def test_get_by_currency(self):
        user = self.factory.make_user()
        book = self.factory.make_book(users=[user])
        account = self.factory.make_account(users=[user])
        kwargs = {'book_slug': book.slug, 'currency': account.currency}
        url = reverse('balance', kwargs=kwargs)

        assert self.client.login(username=user.username, password='test')
        response = self.client.get(url)

        self.assertContains(response, 'Balances for %s' % book.name)
