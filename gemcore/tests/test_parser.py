import csv

from datetime import datetime
from decimal import Decimal

from gemcore.models import Entry
from gemcore.parser import BNABankParser, ScoBankParser, WFGBankParser
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
            rows = [i for i in reader if filter(bool, i)]

        return result, rows, account

    def assert_result(self, result, errors, entries):
        self.assertEqual(len(result['errors']), errors)
        self.assertEqual(len(result['entries']), entries)
        self.assertEqual(Entry.objects.all().count(), entries)

    def assert_entry_correct(self, **kwargs):
        entries = Entry.objects.filter(**kwargs)
        self.assertEqual(entries.count(), 1)


class ParseBNATestCase(ParseBaseTestCase):

    def test_merge_works(self):
        result, rows, account = self.do_parse(BNABankParser(), 'bna-merge.csv')
        self.assert_result(result, errors=1, entries=2)
        self.assertEqual(list(result['errors'].keys()), ['DataMergedError'])
        self.assertEqual(
            list(Entry.objects.all().values_list('amount', 'is_income')),
            [(Decimal('76.41'), True), (Decimal('152.82'), False)])

    def test_real_file(self):
        result, rows, account = self.do_parse(BNABankParser(), 'bna.csv')
        self.assert_result(result, errors=0, entries=225)

        # drop first row, header
        rows = rows[1:]
        for row in rows:
            row = [i for i in row if bool(i)]
            if not row:
                continue
            when = datetime.strptime(row[0], BNABankParser.DATE_FORMAT)
            what = row[1].strip()
            amount = Decimal(row[2])
            is_income = amount > 0
            self.assert_entry_correct(
                account=account, country=BNABankParser.COUNTRY,
                when=when, what=what, amount=abs(amount), is_income=is_income)


class ParseScoTestCase(ParseBaseTestCase):

    def test_real_file(self):
        result, rows, account = self.do_parse(ScoBankParser(), 'sco.csv')
        self.assert_result(result, errors=0, entries=78)

        # drop first row, header
        rows = rows[1:]
        for row in rows:
            if not row:
                continue
            when = datetime.strptime(row[1], ScoBankParser.DATE_FORMAT)
            what = row[3]
            amount = row[5] if row[5] else row[6]
            amount = Decimal(amount.replace('.', '').replace(',', '.'))
            is_income = amount > 0
            self.assert_entry_correct(
                account=account, country=ScoBankParser.COUNTRY,
                when=when, what=what, amount=abs(amount), is_income=is_income)


class ParseWFGTestCase(ParseBaseTestCase):

    def test_real_file(self):
        result, rows, account = self.do_parse(WFGBankParser(), 'wfg.csv')
        self.assert_result(result, errors=0, entries=55)

        last_extra_fee = 0
        for row in rows:
            if not row:
                continue
            when = datetime.strptime(row[0], WFGBankParser.DATE_FORMAT)
            what = row[4]
            amount = Decimal(row[1])
            is_income = amount > 0
            if what in WFGBankParser.EXTRA_FEES:
                last_extra_fee = amount
                continue

            amount = abs(amount) + abs(last_extra_fee)
            self.assert_entry_correct(
                account=account, country=WFGBankParser.COUNTRY,
                when=when, what=what, is_income=is_income, amount=amount)
            last_extra_fee = 0
