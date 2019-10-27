
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


class MultipleRemoveTestCase(BaseTestCase):

    remove_btn = (
        '<button type="submit" class="btn btn-sm btn-default" '
        'name="remove-selected">Remove</button>')

    def do_request(self, user, book, method='GET', **kwargs):
        url = reverse('entries', args=[book.slug])

        assert self.client.login(username=user.username, password='test')
        return getattr(self.client, method.lower())(url, follow=True, **kwargs)

    def test_no_button_shown_if_no_entries(self):
        user = self.factory.make_user()
        book = self.factory.make_book(users=[user])

        response = self.do_request(user, book)

        self.assertNotContains(response, self.remove_btn)

    def test_button_shown_if_entries_available(self):
        user = self.factory.make_user()
        book = self.factory.make_book(users=[user])
        for i in range(3):
            self.factory.make_entry(book=book)

        response = self.do_request(user, book)

        self.assertContains(response, self.remove_btn)

    def test_book_in_context_on_remove_post(self):
        user = self.factory.make_user()
        book = self.factory.make_book(users=[user])
        entries = [
            self.factory.make_entry(book=book) for i in range(3)]

        data = {'entry': [e.id for e in entries], 'remove-selected': 1}
        response = self.do_request(user, book, method='POST', data=data)

        msg = 'Are you sure you want to remove these entries?'
        self.assertContains(response, msg)

        for e in entries:
            msg = '<li>%s<input type="hidden" name="entry" value="%s"/></li>'
            self.assertContains(response, msg % (str(e), e.id))

        self.assertEqual(book, response.context.get('book'))

        url = reverse('remove-entry', args=[book.slug])
        self.assertContains(
            response, '<form action="%s?" method="POST">' % url)
