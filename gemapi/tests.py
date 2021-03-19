import csv
import io
from decimal import Decimal

from django.urls import reverse
from django.test import TestCase

from gemapi.views import TEST_SLUG
from gemcore.models import Book
from gemcore.tests.factory import Factory


class BaseTestCase(TestCase):

    factory = Factory()

    def post_file(self, url, file_content=None):
        if file_content is not None:
            f = io.StringIO(file_content)
            data={'data': f}
        else:
            data=None
        return self.client.post(url, data=data)

    def parse_data(self, data_csv):
        header = ['when', 'is_income', 'amount', 'what']
        csv_reader = csv.reader(io.StringIO(data_csv))
        result = [dict(zip(header, map(str.strip, row))) for row in csv_reader]
        return result

    def get_entries(self):
        entries = Book.objects.get(slug=TEST_SLUG).entry_set.all()
        return list(entries.order_by('id'))

    def assert_entry_correct(self, expected, entry):
        self.assertEqual(entry.when.isoformat(), expected['when'])
        self.assertEqual(entry.amount, Decimal(expected['amount']))
        self.assertEqual(entry.is_income, expected['is_income'] == 'Income')
        self.assertEqual(entry.what, expected['what'])
        self.assertEqual(entry.tags, [TEST_SLUG])
        self.assertEqual(entry.country, 'US')
        self.assertEqual(entry.account.slug, TEST_SLUG)


class TransactionsTestCase(BaseTestCase):

    url = reverse('transactions')

    def do_post(self, file_content=None):
        return self.post_file(self.url, file_content)

    def test_post_no_file(self):
        response = self.do_post(file_content=None)

        self.assertEqual(
            response.json(), {'errors': ['Please upload a data file']})
        self.assertEqual(self.get_entries(), [])

    def test_post_empty_file(self):
        response = self.do_post(file_content='')

        self.assertEqual(response.json(), {'errors': []})
        self.assertEqual(self.get_entries(), [])

    def test_post_invalid_file(self):
        response = self.do_post(file_content='some invalid content')

        self.assertEqual(
            response.json(),
            {'errors': ['IndexError: list index out of range']})
        self.assertEqual(self.get_entries(), [])

    def test_post_ok(self):
        data_csv = (
            '2020-07-01, Expense, 18.77, Fuel\n'
            '# new spark plugs I think\n'
            '2020-07-25, Income, 50.00, 19 Maple Dr.')

        response = self.do_post(data_csv)

        self.assertEqual(response.json(), {'errors': []})

        entries = self.get_entries()
        self.assertEqual(len(entries), 2)
        e1, e2 = entries
        expected1, skip, expected2 = self.parse_data(data_csv)
        self.assert_entry_correct(expected1, e1)
        self.assert_entry_correct(expected2, e2)

    def test_post_errors(self):
        data_csv = (
            '2020-07-01, Expense, 18.77, Fuel\n'
            '# new spark plugs I think\n'
            '2020-07-01, Expense, 18.77, Fuel\n'  # duplicated entry
            '2020-07-25, Income, 50.00, 19 Maple Dr.')

        response = self.do_post(data_csv)

        error = (
            'IntegrityError: duplicate key value violates unique constraint '
            '"gemcore_entry_book_id_account_id_when__bb14242c_uniq"\n'
            'DETAIL:  Key (book_id, account_id, "when", what, amount, '
            'is_income)=(1, 1, 2020-07-01, Fuel, 18.77, f) already exists.\n')
        self.assertEqual(response.json(), {'errors': [error]})

        entries = self.get_entries()
        self.assertEqual(len(entries), 2)
        e1, e2 = entries
        expected1, skip, dupe, expected2 = self.parse_data(data_csv)
        self.assert_entry_correct(expected1, e1)
        self.assert_entry_correct(expected2, e2)


class ReportTestCase(BaseTestCase):

    url = reverse('report')

    def do_get(self, **kwargs):
        return self.client.get(self.url, **kwargs)

    def test_no_entries(self):
        assert self.get_entries() == []

        response = self.do_get()

        self.assertEqual(response.json(), {})

    def test_other_books_ignored(self):
        self.factory.make_entry()
        self.factory.make_entry()
        assert self.get_entries() == []

        response = self.do_get()

        self.assertEqual(response.json(), {})

    def test_balance_calculated(self):
        book = Book.objects.get(slug=TEST_SLUG)
        e1 = self.factory.make_entry(book=book, amount=23.0, is_income=True)
        e2 = self.factory.make_entry(book=book, amount=18.0, is_income=False)
        assert self.get_entries() == [e1, e2]

        response = self.do_get()

        self.assertEqual(
            response.json(),
            {'expenses': 18.0, 'gross-revenue': 23.0, 'net-revenue': 5.0})

    def test_integration(self):
        data_csv = (
            '2020-07-01, Expense, 18.77, Fuel\n'
            '2020-07-04, Income, 40.00, 347 Woodrow\n'
            '2020-07-06, Income, 35.00, 219 Pleasant\n'
            '# new spark plugs I think\n'
            '2020-07-12, Expense, 27.50, Repairs\n'
            '2020-07-15, Income, 25.00, Blackburn St.\n'
            '2020-07-16, Expense, 12.45, Fuel\n'
            '2020-07-22, Income, 35.00, 219 Pleasant\n'
            '2020-07-22, Income, 40.00, 347 Woodrow\n'
            '2020-07-25, Expense, 14.21, Fuel\n'
            '2020-07-25, Income, 50.00, 19 Maple Dr.\n')

        response = self.post_file(TransactionsTestCase.url, data_csv)
        self.assertEqual(response.json(), {'errors': []})

        response = self.do_get()
        self.assertEqual(
            response.json(),
            {'expenses': 72.93, 'gross-revenue': 225.0, 'net-revenue': 152.07})
