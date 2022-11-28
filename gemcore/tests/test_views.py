from django.urls import reverse

from gemcore.models import TAGS
from gemcore.tests.helpers import BaseTestCase


class AddEntryTestCase(BaseTestCase):
    def test_integrity_error_handled(self):
        user = self.factory.make_user()
        assert self.client.login(username=user.username, password='test')
        book = self.factory.make_book(users=[user])
        account = self.factory.make_account(users=[user])
        existing = self.factory.make_entry(
            book=book,
            account=account,
            who=user,
            amount=10,
            what='test',
            tags=['food'],
            country='US',
        )
        url = reverse('add-entry', kwargs={'book_slug': book.slug})

        data = dict(
            who=user.id,
            amount=10,
            what='test',
            country='US',
            when=existing.when.isoformat(),
            account=account.id,
            tags=['food'],
        )
        response = self.client.post(url, data=data, follow=True)

        error = 'There is already an entry for this data.'
        form = response.context['form']
        self.assertFormError(form, field=None, errors=[error])


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


class BulkTestCaseMixin:

    action_name = ''
    action_btn = None

    def do_request(self, user, book, method='GET', **kwargs):
        url = reverse('entries', args=[book.slug])

        assert self.client.login(username=user.username, password='test')
        return getattr(self.client, method.lower())(url, follow=True, **kwargs)

    def test_no_action_shown_if_no_entries(self):
        user = self.factory.make_user()
        book = self.factory.make_book(users=[user])

        response = self.do_request(user, book)

        assert self.action_btn is not None
        self.assertNotContains(response, self.action_btn)

    def test_button_shown_if_entries_available(self):
        user = self.factory.make_user()
        book = self.factory.make_book(users=[user])
        for i in range(3):
            self.factory.make_entry(book=book)

        response = self.do_request(user, book)

        self.assertContains(response, self.action_btn)


class BulkRemoveTestCase(BulkTestCaseMixin, BaseTestCase):

    action_name = 'remove-selected'
    action_btn = (
        '<button type="submit" class="btn btn-sm btn-default" '
        f'name="{action_name}">Remove</button>'
    )

    def test_book_in_context_on_remove_post(self):
        user = self.factory.make_user()
        book = self.factory.make_book(users=[user])
        entries = [self.factory.make_entry(book=book) for i in range(3)]

        assert self.action_name
        data = {'entry': [e.id for e in entries], self.action_name: 1}
        response = self.do_request(user, book, method='POST', data=data)

        msg = 'Are you sure you want to remove these entries?'
        self.assertContains(response, msg)

        for e in entries:
            msg = '<li>%s<input type="hidden" name="entry" value="%s"/></li>'
            self.assertContains(response, msg % (str(e), e.id))

        self.assertEqual(book, response.context.get('book'))

        url = reverse('remove-entry', args=[book.slug])
        self.assertContains(
            response, '<form action="%s?" method="POST">' % url
        )


class BulkMergeTestCase(BulkTestCaseMixin, BaseTestCase):

    action_name = 'merge-selected'
    action_btn = (
        '<button type="submit" class="btn btn-sm btn-default" '
        f'name="{action_name}">Merge</button>'
    )


class BulkChangeAccountTestCase(BulkTestCaseMixin, BaseTestCase):

    action_name = 'change-account'
    action_btn = (
        '<button type="submit" class="btn btn-sm btn-default" '
        f'name="{action_name}">Change account</button>'
    )


class BulkChangeTagTestCase(BulkTestCaseMixin, BaseTestCase):

    action_name = 'change-tags'
    action_btn = (
        '<button type="submit" class="btn btn-sm btn-default" '
        f'name="{action_name}">Change tag</button>'
    )

    def test_tags_changed(self):
        user = self.factory.make_user()
        book = self.factory.make_book(users=[user])
        # make many entries
        unchanged = [
            self.factory.make_entry(book=book, tags=[t]) for t in TAGS
        ]
        entries = [self.factory.make_entry(book=book, tags=[t]) for t in TAGS]

        assert self.action_name
        target_tag = TAGS[0]
        data = {
            'entry': [e.id for e in entries],
            self.action_name: 1,
            'tags-target': target_tag,
        }
        response = self.do_request(user, book, method='POST', data=data)

        self.assertRedirects(response, reverse('entries', args=[book.slug]))
        msg = ', '.join(str(e) for e in entries)
        self.assert_messages(
            response,
            error=[],
            success=[f'Entries "{msg}" changed with tags {target_tag}.'],
        )
        for e in entries:
            e.refresh_from_db()
            self.assertEqual(e.tags, [target_tag])
        for i, e in enumerate(unchanged):
            e.refresh_from_db()
            self.assertEqual(e.tags, unchanged[i].tags)
