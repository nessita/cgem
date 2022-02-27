import csv

from datetime import datetime
from decimal import Decimal
from io import StringIO

from gemcore.models import Entry
from gemcore.parser import CSVParser
from gemcore.tests.helpers import BaseTestCase


class CSVParserTestCase(BaseTestCase):
    def make_account_with_parser(self, **kwargs):
        parser = self.factory.make_parser_config(**kwargs)
        user = self.factory.make_user()
        account = self.factory.make_account(users=[user], parser_config=parser)
        return account

    def do_parse(self, account, stream, book=None):
        user = account.users.get()
        if book is None:
            book = self.factory.make_book(users=[user])

        result = CSVParser(account).parse(stream, book=book, user=user)
        stream.seek(0)
        reader = csv.reader(stream)
        rows = [i for i in reader if filter(bool, i)]

        return result, rows

    def assert_result(self, result, errors, entries, all_entries=None):
        self.assertEqual(
            len(result['errors']),
            errors,
            'Expected %r errors (got %s %s instead).'
            % (errors, len(result['errors']), result['errors']),
        )
        self.assertEqual(len(result['entries']), entries)
        if all_entries is None:
            all_entries = entries
        self.assertEqual(Entry.objects.all().count(), all_entries)

    def assert_entry_correct(self, **kwargs):
        entries = Entry.objects.filter(**kwargs)
        self.assertEqual(entries.count(), 1)

    def test_duplicated_entry(self):
        account = self.make_account_with_parser(
            when=[0], what=[1], amount=[2, 3], country='US'
        )
        user = account.users.get()
        book = self.factory.make_book(users=[user])

        f = StringIO("2021-10-21,line 1,10,0\n" "2021-10-21,line 2,0,20\n")
        result, rows = self.do_parse(account, f, book)
        self.assert_result(result, errors=0, entries=2)

        f = StringIO("2021-10-21,line 2,0,20")
        result, rows = self.do_parse(account, f, book)

        self.assert_result(result, errors=1, entries=0, all_entries=2)
        data = {
            'account': account.pk,
            'amount': Decimal('20'),
            'country': 'US',
            'is_income': True,
            'notes': "source: 'stream with no name'",
            'tags': ['imported'],
            'what': 'line 2',
            'when': datetime(2021, 10, 21, 0, 0),
            'who': user.pk,
        }
        error = {
            'exception': 'ValueError',
            'message': '__all__: There is already an entry for this data.',
            'data': data,
        }
        self.assertEqual(result['errors'], [error])

    def test_index_error(self):
        account = self.make_account_with_parser(
            when=[0], what=[1], amount=[2, 3], country='ES'
        )

        f = StringIO(
            "2021-10-21,line 1,10,0\n"
            "hola mono\n"
            "2021-10-21,line 2,0,20\n"
            ""
        )
        result, rows = self.do_parse(account, f)

        self.assert_result(result, errors=1, entries=2)
        error = {
            'exception': 'IndexError',
            'message': 'list index out of range',
            'data': ['hola mono'],
        }
        self.assertEqual(result['errors'], [error])

    def test_bank1(self):
        # Fecha / Hora Mov.,Concepto,Importe,Comentarios,Saldo Parcial
        account = self.make_account_with_parser(
            when=[0],
            what=[1],
            amount=[2],
            notes=[3, 4],
            date_format='%d/%m/%Y',
            country='FR',
            ignore_rows=1,
        )

        fname = self.data_file('bank1.csv')
        with open(fname) as f:
            result, rows = self.do_parse(account, f)
        self.assert_result(result, errors=0, entries=225)

        # drop first row, header
        rows = rows[1:]
        for row in rows:
            row = [i for i in row if bool(i)]
            if not row or not any(row):
                continue
            when = datetime.strptime(row[0], account.parser_config.date_format)
            what = row[1].strip()
            amount = Decimal(row[2])
            is_income = amount > 0
            self.assert_entry_correct(
                account=account,
                country=account.parser_config.country,
                when=when,
                what=what,
                amount=abs(amount),
                is_income=is_income,
            )

    def test_bank2(self):
        # "Suc.","Fecha","Fecha Valor","Descripción","Comprobante",
        # "Débito","Crédito","Saldo"
        account = self.make_account_with_parser(
            when=[1, 2],
            what=[3],
            amount=[5, 6],
            notes=[0, 4, 7],
            date_format='%d/%m/%Y',
            country='ES',
            ignore_rows=1,
            thousands_sep='.',
            decimal_point=',',
        )

        fname = self.data_file('bank2.csv')
        with open(fname) as f:
            result, rows = self.do_parse(account, f)
        self.assert_result(result, errors=0, entries=78)

        # drop first row, header
        rows = rows[1:]
        for row in rows:
            if not row:
                continue
            when = datetime.strptime(row[1], '%d/%m/%Y')
            what = row[3]
            amount = row[5] if row[5] else row[6]
            amount = Decimal(amount.replace('.', '').replace(',', '.'))
            is_income = amount > 0
            self.assert_entry_correct(
                account=account,
                country=account.parser_config.country,
                when=when,
                what=what,
                amount=abs(amount),
                is_income=is_income,
            )

    def test_bank3(self):
        # ,Fecha,,Descripción,Número Documento,Num. Dep.,Asunto,,Débito,Crédito
        account = self.make_account_with_parser(
            when=[1],
            what=[3],
            amount=[8, 9],
            notes=[4, 5, 6],
            date_format='%d/%m/%Y',
            country='IT',
            ignore_rows=6,
        )

        fname = self.data_file('bank3.csv')
        with open(fname) as f:
            result, rows = self.do_parse(account, f)
        self.assert_result(result, errors=0, entries=21)

        # drop dummy rows
        rows = rows[6:]
        for row in rows:
            if not row:
                continue
            when = datetime.strptime(row[1], '%d/%m/%Y')
            what = row[3].strip()
            if row[8]:
                amount = Decimal(row[8].replace(',', ''))
                is_income = False
            else:
                amount = Decimal(row[9].replace(',', ''))
                is_income = True
            self.assert_entry_correct(
                account=account,
                country=account.parser_config.country,
                when=when,
                what=what,
                amount=abs(amount),
                is_income=is_income,
            )

    def test_bank4(self):
        defer = [
            'INTERNATIONAL PURCHASE TRANSACTION FEE',
            'NON-WELLS FARGO ATM TRANSACTION FEE',
        ]
        account = self.make_account_with_parser(
            when=[0],
            what=[4],
            amount=[1],
            date_format='%m/%d/%Y',
            country='NZ',
            defer_processing=defer,
            ignore_rows=0,
        )

        fname = self.data_file('bank4.csv')
        with open(fname) as f:
            result, rows = self.do_parse(account, f)
        self.assert_result(result, errors=0, entries=54)

        last_extra_fee = 0
        for row in rows:
            if not row:
                continue
            when = datetime.strptime(row[0], '%m/%d/%Y')
            what = row[4]
            amount = Decimal(row[1])
            is_income = amount > 0
            if what in defer:
                last_extra_fee = amount
                continue

            amount = abs(amount) + abs(last_extra_fee)
            self.assert_entry_correct(
                account=account,
                country=account.parser_config.country,
                when=when,
                what=what,
                is_income=is_income,
                amount=amount,
            )
            last_extra_fee = 0
