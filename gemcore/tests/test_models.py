# -*- coding: utf-8 -*-

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.db import IntegrityError
from django.utils.timezone import now

from gemcore.models import TAGS, Entry
from gemcore.tests.helpers import BaseTestCase


class BookTestCase(BaseTestCase):

    def setUp(self):
        super(BookTestCase, self).setUp()
        for u in ('user1', 'user2', 'other'):
            setattr(self, u, self.factory.make_user(username=u))
        self.book = self.factory.make_book(
            name='our-expenses-test', users=[self.user1, self.user2])

    def test_balance_one_account(self, account=None):
        # no entries
        balance = self.book.balance(Entry.objects.none())
        self.assertIsNone(balance)

        if account is None:
            account = self.factory.make_account()

        # add some entries, $1 each, all but one the same day
        when = now().date()
        self.factory.make_entry(book=self.book, account=account, when=when)
        self.factory.make_entry(book=self.book, account=account, when=when)
        self.factory.make_entry(
            book=self.book, account=account, when=when, is_income=True)
        other_when = when + timedelta(days=31)
        self.factory.make_entry(
            book=self.book, account=account, when=other_when)

        other_first_of_month = date(other_when.year, other_when.month, 1)
        balance = self.book.balance(
            entries=Entry.objects.filter(account=account))
        expected = {
            'complete': {
                'expense': Decimal('3.00'),
                'income': Decimal('1.00'),
                'result': Decimal('-2.00'),
                'start': when,
                'end': other_when,
            },
            'months': [{
                'expense': Decimal('2.00'),
                'income': Decimal('1.00'),
                'result': Decimal('-1.00'),
                'start': date(when.year, when.month, 1),
                'end': other_first_of_month - timedelta(days=1),
            }, {
                'expense': Decimal('1.00'),
                'income': Decimal('0'),
                'result': Decimal('-1.00'),
                'start': other_first_of_month,
                'end': other_when,
            }]
        }
        self.assertEqual(balance, expected)

    def test_balance_many_accounts_for_book_request_one(self):
        account1 = self.factory.make_account()
        account2 = self.factory.make_account()
        account = self.factory.make_account()

        self.factory.make_entry(book=self.book, account=account1)
        self.factory.make_entry(book=self.book, account=account1)

        self.factory.make_entry(book=self.book, account=account2)
        self.factory.make_entry(book=self.book, account=account2)
        self.factory.make_entry(book=self.book, account=account2)

        self.test_balance_one_account(account=account)

    def test_balance_many_accounts(self):
        # add some accounts with entries, $1 each, all but one the same day
        when = now().date()
        for i in range(1, 4):
            account = self.factory.make_account()
            for j in range(i):
                self.factory.make_entry(
                    book=self.book, account=account, when=when)

        balance = self.book.balance()
        expected = {
            'complete': {
                'expense': Decimal('6.00'),
                'income': Decimal('0'),
                'result': Decimal('-6.00'),
                'start': when,
                'end': when,
            },
            'months': [{
                'expense': Decimal('6.00'),
                'income': Decimal('0'),
                'result': Decimal('-6.00'),
                'start': date(when.year, when.month, 1),
                'end': when,
            }]
        }
        self.assertEqual(balance, expected)

    def assert_merge_entries_value_error(self, *entries, expected_error):
        with self.assertRaises(ValueError) as ctx:
            self.book.merge_entries(*entries)
        self.assertEqual(str(ctx.exception), expected_error)

    def test_merge_entries_validations(self):
        account1 = self.factory.make_account()
        entry1 = self.factory.make_entry(book=self.book, account=account1)

        self.assert_merge_entries_value_error(
            entry1, expected_error='Need at least 2 entries to merge (got 1).')

        other = self.factory.make_entry(
            book=self.factory.make_book(slug='zzz'), account=account1)
        assert other.book != entry1.book

        expected = 'Can not merge entries outside this book (got %s, %s).'
        self.assert_merge_entries_value_error(
            entry1, other,
            expected_error=expected % (self.book.slug, other.book.slug))

        othercountry = self.factory.make_entry(
            book=self.book, account=account1, country='XX')
        assert othercountry.country != entry1.country
        expected = 'Can not merge entries for different countries (got %s).'
        self.assert_merge_entries_value_error(
            entry1, othercountry, expected_error=expected % 'AR, XX')

        account2 = self.factory.make_account(slug='zzz')
        entry2 = self.factory.make_entry(book=self.book, account=account2)

        expected = 'Can not merge entries for different accounts (got %s, %s).'
        self.assert_merge_entries_value_error(
            entry1, entry2,
            expected_error=expected % (account1.slug, account2.slug))

    def test_merge_entries(self):
        account = self.factory.make_account()

        # create many other entries to ensure nothing else is removed
        must_be_kept = ([
            self.factory.make_entry(book=self.book, account=account)
            for i in range(3)] +
            [self.factory.make_entry(account=account) for i in range(3)] +
            [self.factory.make_entry(book=self.book) for i in range(3)] +
            [self.factory.make_entry() for i in range(3)])

        entries = [
            self.factory.make_entry(
                book=self.book, account=account, amount=Decimal(i),
                tags=[TAGS[i]], is_income=False, what='Dummy')
            for i in range(5)]
        target = self.factory.make_entry(
            book=self.book, account=account, amount=Decimal('100.88'),
            is_income=True, tags=[TAGS[-1]], what='A target entry')
        ids = [e.id for e in entries] + [target.id]

        before_count = len(must_be_kept) + len(ids)
        assert Entry.objects.all().count() == before_count

        # from_dry_run =
        self.book.merge_entries(target, *entries, dry_run=True)
        self.assertEqual(Entry.objects.all().count(), before_count)
        for e in [target] + entries + must_be_kept:
            self.assertEqual(Entry.objects.get(id=e.id), e)

        result = self.book.merge_entries(target, *entries)

        self.assertEqual(result.book, self.book)
        self.assertEqual(result.who, target.who)
        self.assertEqual(result.when, target.when)
        expected = ('A target entry +$100.88 | Dummy -$0 | Dummy -$1 | '
                    'Dummy -$2 | Dummy -$3 | Dummy -$4')
        self.assertEqual(result.what, expected)
        self.assertEqual(result.account, account)
        self.assertEqual(result.amount, Decimal('90.88'))
        self.assertEqual(result.is_income, True)
        self.assertEqual(result.labels, [TAGS[-1]] + TAGS[:5])
        self.assertEqual(result.country, target.country)
        self.assertEqual(Entry.objects.last(), result)
        self.assertNotIn(result.id, ids)
        # self.assertEqual(result, from_dry_run)

        self.assertEqual(Entry.objects.all().count(), len(must_be_kept) + 1)
        for e in must_be_kept:
            self.assertEqual(Entry.objects.get(id=e.id), e)

    def test_merge_entries_all_expenses(self):
        account = self.factory.make_account()

        entries = [
            self.factory.make_entry(
                book=self.book, account=account, amount=Decimal(i),
                is_income=False)
            for i in range(1, 50, 3)]

        result = self.book.merge_entries(*entries)

        self.assertEqual(result.account, account)
        self.assertEqual(result.amount, Decimal(sum(range(1, 50, 3))))
        self.assertEqual(result.is_income, False)

    def test_merge_entries_all_income(self):
        account = self.factory.make_account()

        entries = [
            self.factory.make_entry(
                book=self.book, account=account, amount=Decimal(i),
                is_income=True)
            for i in range(1, 50, 3)]

        result = self.book.merge_entries(*entries)

        self.assertEqual(result.account, account)
        self.assertEqual(result.amount, Decimal(sum(range(1, 50, 3))))
        self.assertEqual(result.is_income, True)

    def test_merge_entries_atomic(self):
        account = self.factory.make_account()
        # create another entry that will make the creation fail
        initial = self.factory.make_entry(
            book=self.book, account=account, what='foo', amount=Decimal(10))

        entries = [
            self.factory.make_entry(
                book=self.book, account=account, what='foo', amount=Decimal(i))
            for i in range(5)]

        with self.assertRaises(IntegrityError):
            self.book.merge_entries(*entries, what='foo')

        self.assertEqual(Entry.objects.all().count(), len(entries) + 1)
        for e in entries + [initial]:
            self.assertEqual(Entry.objects.get(id=e.id), e)

    def test_merge_entries_atomic_if_delete_fails(self):
        account = self.factory.make_account()

        entries = [
            self.factory.make_entry(
                book=self.book, account=account, what='foo', amount=Decimal(i))
            for i in range(5)]

        with patch('gemcore.models.Entry.objects.filter',
                   side_effect=TypeError('foo')):
            with self.assertRaises(TypeError):
                self.book.merge_entries(*entries)

        self.assertEqual(Entry.objects.all().count(), len(entries))
        for e in entries:
            self.assertEqual(Entry.objects.get(id=e.id), e)

    def test_breakdown(self):
        for i, t in enumerate(TAGS, start=1):
            for j in range(i):
                self.factory.make_entry(book=self.book, tags=[t])
                if j % 2:
                    self.factory.make_entry(
                        book=self.book, tags=[t], is_income=True)

        self.book.breakdown()


class AccountTestCase(BaseTestCase):

    def test_tags_for(self):
        account = self.factory.make_account()
        self.factory.make_tag_regex(
            regex='\d{2}', tag='house', account=account)
        self.factory.make_tag_regex(
            regex='^[a-zA-Z ]+$', tag='food', account=account)
        self.factory.make_tag_regex(
            regex='\d{2}[a-z]', tag='fun', account=account)
        self.factory.make_tag_regex(
            regex='HOLA MANOLA', tag='trips', account=account)

        self.assertCountEqual(account.tags_for(''), [])
        self.assertCountEqual(account.tags_for('HOLA'), ['food'])
        self.assertCountEqual(account.tags_for('HOLA '), ['food'])
        self.assertCountEqual(
            account.tags_for('HOLA MANOLA'), ['food', 'trips'])
        self.assertCountEqual(account.tags_for('HOLA MANOLA ---'), ['trips'])
        self.assertCountEqual(account.tags_for('HOLA MAN'), ['food'])
        self.assertCountEqual(account.tags_for('foo'), ['food'])
        self.assertCountEqual(account.tags_for('12x'), ['fun', 'house'])
        self.assertCountEqual(account.tags_for('y12x'), [])
