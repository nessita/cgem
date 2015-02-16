# /usr/bin/env python3

import csv
import os
import sys

if __name__ == '__main__':
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gem.settings')
    django.setup()

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from collections import namedtuple
from django.contrib.auth.models import User
from gemcore.forms import EntryForm
from gemcore.models import Account, Book

UserData = namedtuple('UserData', ['user', 'account'])

TAGS_MAPPING = {
    'Comida/super': ['food'],
    'Gastos fijos': ['taxes', 'utilities'],
    'Mantenimiento': ['maintainance'],
    'Otros': ['other'],
    'Recreacion': ['fun'],
    'Salud': ['health'],
    'Transporte': ['travel (transport)'],
    'Auto': ['car'],
}
AMOUNT = 'How much'
COUNTRY = 'Country'
KIND = 'Kind'
WHEN = 'When'
WHO = 'Who'
WHY = 'Why'
WHAT = 'What'


class CSVParser(object):

    HEADER = []
    IGNORE_ROWS = 0

    def __init__(self, book=None):
        super(CSVParser, self).__init__()
        if book is None:
            book = Book.objects.get(slug='our-expenses')
        self.book = book
        self.name = None
        self.matiasb = User.objects.get(username='matiasb')
        self.nessita = User.objects.get(username='nessita')

    def check_header(self, row):
        assert self.HEADER == row, (
            'The header %s is not the expected %s' % (row, self.HEADER))

    def process_row(self, row):
        return {}

    def process_data(self, data):
        form = EntryForm(data=data)
        if not form.is_valid():
            raise ValueError(form.errors)
        return form.save(book=self.book)

    def parse(self, fileobj):
        self.name = fileobj.name
        header = None
        result = dict(entries=[], errors=defaultdict(list))

        reader = csv.reader(fileobj)
        ignored = 0
        for row in reader:
            # ignore initial rows
            if ignored < self.IGNORE_ROWS:
                ignored += 1
                continue

            # ignore empty values at the end
            while row and not row[-1]:
                row.pop()

            if header is None:
                self.check_header(row)
                header = row
                continue

            row = {h: d for h, d in zip(header, row)}
            try:
                data = self.process_row(row)
                entry = self.process_data(data)
            except Exception as e:
                result['errors'][e.__class__.__name__].append((e, row))
            else:
                result['entries'].append(entry)

        return result


class ExpenseCSVParser(CSVParser):

    HEADER = [
        WHEN, WHO, WHY, WHAT, AMOUNT, 'Summary category', 'Summary amount']

    def __init__(self, *args, **kwargs):
        super(ExpenseCSVParser, self).__init__(*args, **kwargs)
        matiasb = UserData(
            user=self.matiasb,
            account=Account.objects.get(slug='cash-ars-matiasb'))
        nessita = UserData(
            user=self.nessita,
            account=Account.objects.get(slug='cash-ars-nessita'))
        self.users = {'M': matiasb, 'N': nessita}

    def process_row(self, row):
        userdata = self.users[row[WHO]]
        amount = row[AMOUNT].strip('$').replace(',', '')
        data = dict(
            who=userdata.user.id,
            when=datetime.strptime(row[WHEN], '%Y-%m-%d'),
            what=row[WHY],
            account=userdata.account.id,
            amount=Decimal(amount),
            is_income=False,
            country='AR',
            tags=TAGS_MAPPING[row[WHAT]],
        )
        return data


class BankCSVParser(CSVParser):

    HEADER = [WHEN, WHO, WHY, AMOUNT, 'Total', WHAT, KIND]

    def __init__(self, *args, **kwargs):
        super(BankCSVParser, self).__init__(*args, **kwargs)
        self.account = Account.objects.get(slug='disc-usd-shared')
        self.extra = defaultdict(dict)

    def process_data(self, data):
        if data:
            return super(BankCSVParser, self).process_data(data)

    def process_row(self, row):
        amount = row[AMOUNT]
        what = row[WHY]
        when = datetime.strptime(row[WHEN], '%Y-%m-%d')
        bank_id = row[WHO]

        if row[KIND] == 'U$B':
            assert bank_id not in self.extra[when]
            self.extra[when][bank_id] = ' '.join((what, amount))
            return None

        assert row[KIND] == 'U$T'  # real entry

        extra = self.extra[when]
        if extra:
            notes = []
            for bid, info in extra.items():
                notes.append('%s: %s' % (bid, info))
            notes = '\n'.join(notes)
        else:
            notes = bank_id

        amount = Decimal(amount.replace('$', ''))
        if amount < 0:
            is_income = False
            amount = amount * -1
        else:
            is_income = True
        data = dict(
            who=self.nessita.id, when=when, what='%s: %s' % (bank_id, what),
            notes=notes, account=self.account.id,
            amount=amount, is_income=is_income,
            country='UY', tags=['imported'],
        )
        return data


class TripCSVParser(CSVParser):

    HEADER = [WHEN, WHO, WHAT, COUNTRY]
    IGNORE_ROWS = 4

    def __init__(self, *args, **kwargs):
        super(TripCSVParser, self).__init__(*args, **kwargs)
        self.currencies = None
        self.users = {
            'ARS': {
                'M': UserData(
                        user=self.matiasb,
                        account=Account.objects.get(slug='cash-ars-matiasb')),
                'N': UserData(
                        user=self.nessita,
                        account=Account.objects.get(slug='cash-ars-nessita')),
                'X': UserData(
                        user=self.nessita,
                        account=Account.objects.get(slug='cash-ars-shared')),
            },
            'UYU': {
                'X': UserData(
                        user=self.nessita,
                        account=Account.objects.get(slug='cash-uyu-shared')),
            },
            'USD':{
                'M': UserData(
                        user=self.matiasb,
                        account=Account.objects.get(slug='cash-usd-matiasb')),
                'N': UserData(
                        user=self.nessita,
                        account=Account.objects.get(slug='cash-usd-nessita')),
                'X': UserData(
                        user=self.nessita,
                        account=Account.objects.get(slug='cash-usd-shared')),
            },
            'EUR':{
                'M': UserData(
                        user=self.matiasb,
                        account=Account.objects.get(slug='cash-eur-matiasb')),
                'N': UserData(
                        user=self.nessita,
                        account=Account.objects.get(slug='cash-eur-nessita')),
                'X': UserData(
                        user=self.nessita,
                        account=Account.objects.get(slug='cash-eur-shared')),
            },
        }

    def check_header(self, row):
        header_len = len(self.HEADER)
        assert self.HEADER == row[:header_len], (
            'The header %s is not the expected %s' % (row, self.HEADER))
        self.currencies = row[header_len:]

    def process_row(self, row):
        amount = None
        currency = None
        for c in self.currencies:
            if row[c]:
                amount = row[c].strip('$').replace(',', '')
                currency = c
                break

        assert amount is not None

        userdata = self.users[currency][row[WHO]]
        data = dict(
            who=userdata.user.id,
            when=datetime.strptime(row[WHEN], '%Y-%m-%d'),
            what=row[WHAT],
            notes=self.name,
            account=userdata.account.id,
            amount=Decimal(amount),
            is_income=False,
            country=row[COUNTRY],
            tags=['trips'],
        )
        return data


if __name__ == '__main__':
    parser = TripCSVParser()
    filename = sys.argv[1]
    print(filename)
    with open(filename) as f:
        result = parser.parse(fileobj=f)
    for error, traceback in result['errors'].items():
        print('=== ERROR ===', error)
        print(traceback)
        print('\n\n')
