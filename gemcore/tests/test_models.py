# -*- coding: utf-8 -*-

from datetime import date, timedelta
from decimal import Decimal

from django.utils.timezone import now

from gemcore.tests.helpers import BaseTestcase


class BookTestCase(BaseTestCase):

    def setUp(self):
        super(BookTestCase, self).setUp()
        for u in ('user1', 'user2', 'other'):
            setattr(self, u, self.factory.make_user(username=u))
        self.book = self.factory.make_book(
            name='our-expenses-test', users=[self.user1, self.user2])

    def test_balance_one_account(self, account=None):
        if account is None:
            account = self.factory.make_account()

        # no entries
        balance = self.book.balance(account)
        self.assertIsNone(balance)

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
        balance = self.book.balance(account)
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
