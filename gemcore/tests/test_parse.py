import csv

from datetime import datetime
from decimal import Decimal

from gemcore.models import Entry
from gemcore.parse import ScoBankCSVParser, WFGBankCSVParser
from gemcore.tests.helpers import BaseTestCase


class ParseBaseTestCase(BaseTestCase):

    def do_parse(self, parser, csv_name, account=None, book=None):
        user = self.factory.make_user()
        if account is None:
            account = self.factory.make_account(
                users=[user], parser=parser.__class__.__name__)
        if book is None:
            book = self.factory.make_book(users=[user])

        fname = self.data_file(csv_name)
        with open(fname) as f:
            result = parser.parse(f, book=book, user=user, account=account)
            f.seek(0)
            reader = csv.reader(f)
            rows = [i for i in reader if filter(None, i)]

        return result, rows


class ParseScoTestCase(ParseBaseTestCase):

    def test_parse_real_file(self):
        result, rows = self.do_parse(ScoBankCSVParser(), 'sco.csv')

        self.assertEqual(result['errors'], {})
        self.assertEqual(len(result['entries']), 78)
        self.assertEqual(Entry.objects.all().count(), len(result['entries']))

        # drop first row, header
        rows = rows[1:]
        for row in rows:
            if not row:
                continue
            when = datetime.strptime(row[1], ScoBankCSVParser.DATE_FORMAT)
            what = row[3]
            amount = row[5] if row[5] else row[6]
            amount = Decimal(amount.replace('.', '').replace(',', '.'))
            is_income = amount > 0
            entries = Entry.objects.filter(
                when=when, what=what, amount=abs(amount), is_income=is_income)
            self.assertEqual(entries.count(), 1)


class ParseWFGTestCase(ParseBaseTestCase):

    def test_parse_real_file(self):
        result, rows = self.do_parse(WFGBankCSVParser(), 'wfg.csv')

        self.assertEqual(result['errors'], {})
        self.assertEqual(len(result['entries']), 55)
        self.assertEqual(Entry.objects.all().count(), len(result['entries']))

        last_extra_fee = 0
        for row in rows:
            if not row:
                continue
            when = datetime.strptime(row[0], WFGBankCSVParser.DATE_FORMAT)
            what = row[4]
            amount = Decimal(row[1])
            is_income = amount > 0
            if what in WFGBankCSVParser.EXTRA_FEES:
                last_extra_fee = amount
                continue

            amount = abs(amount) + abs(last_extra_fee)
            entries = Entry.objects.filter(
                when=when, what=what, is_income=is_income, amount=amount)
            self.assertEqual(entries.count(), 1)
            last_extra_fee = 0
