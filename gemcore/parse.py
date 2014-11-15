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
    'Transporte': ['travel'],
    'Auto': ['car'],
}
AMOUNT = 'How much'
KIND = 'Kind'
WHEN = 'When'
WHO = 'Who'
WHY = 'Why'
WHAT = 'What'


class CSVParser(object):

    HEADER = []

    def __init__(self, book=None):
        super(CSVParser, self).__init__()
        if book is None:
            book = Book.objects.get(slug='our-expenses')
        self.book = book

    def process_row(self, row):
        return {}

    def process_data(self, data):
        form = EntryForm(data=data)
        if not form.is_valid():
            raise ValueError(form.errors)
        return form.save(book=self.book)

    def parse(self, fileobj):
        header = None
        result = dict(entries=[], errors=defaultdict(list))

        reader = csv.reader(fileobj)
        for row in reader:
            row = [r.strip() for r in row if r]
            if header is None:
                assert self.HEADER == row, (
                    'The header %s is not the expected %s' %
                    (row, self.HEADER))
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

    def __init__(self, book=None):
        super(ExpenseCSVParser, self).__init__(book=book)
        matiasb = UserData(
            user=User.objects.get(username='matiasb'),
            account=Account.objects.get(slug='cash-ars-matiasb'))
        nessita = UserData(
            user=User.objects.get(username='nessita'),
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

    def __init__(self, book=None):
        super(BankCSVParser, self).__init__(book=book)
        self.user = User.objects.get(username='nessita')
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
            who=self.user.id, when=when, what='%s: %s' % (bank_id, what),
            notes=notes, account=self.account.id,
            amount=amount, is_income=is_income,
            country='UY', tags=['imported'],
        )
        return data


if __name__ == '__main__':
    parser = BankCSVParser()
    filename = sys.argv[1]
    print(filename)
    with open(filename) as f:
        result = parser.parse(fileobj=f)
    if result['errors']:
        print('=== ERROR ===', result['errors'].keys())
