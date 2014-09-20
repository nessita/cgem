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
from django.db.utils import IntegrityError
from django.contrib.auth.models import User
from gemcore.forms import EntryForm
from gemcore.models import Account, Book

UserData = namedtuple('UserData', ['user', 'account'])

CATEGORY_MAPPING = {
    'Comida/super': 'food',
    'Gastos fijos': 'taxes, utilities',
    'Mantenimiento': 'maintainance',
    'Otros': 'other',
    'Recreacion': 'fun',
    'Salud': 'health',
    'Transporte': 'travel',
    'Auto': 'car',
}
WHEN = 'When'
WHO = 'Who'
WHY = 'Why'
WHAT = 'What'
AMOUNT = 'How much'
HEADER = [WHEN, WHO, WHY, WHAT, AMOUNT, 'Summary category', 'Summary amount']


class ExpenseCSVParser(object):

    def __init__(self, book=None):
        super(ExpenseCSVParser, self).__init__()
        matiasb = UserData(
            user=User.objects.get(username='matiasb'),
            account=Account.objects.get(slug='cash-ars-matiasb'))
        nessita = UserData(
            user=User.objects.get(username='nessita'),
            account=Account.objects.get(slug='cash-ars-nessita'))
        self.users = {'M': matiasb, 'N': nessita}
        if book is None:
            book = Book.objects.get(slug='our-expenses')
        self.book = book

    def process_row(self, row):
        userdata = self.users[row[WHO]]
        amount = row[AMOUNT].strip('$').replace(',', '')
        what = row[WHY]
        tags = CATEGORY_MAPPING[row[WHAT]]

        data = dict(
            who=userdata.user.id,
            when=datetime.strptime(row[WHEN], '%Y-%m-%d'),
            what=what,
            account=userdata.account.id,
            amount=Decimal(amount),
            is_income=False,
            tags=tags,
        )
        form = EntryForm(data=data)
        assert form.is_valid(), form.errors

        return form.save(book=self.book)

    def parse(self, fileobj):
        header = None
        result = dict(entries=[], errors=defaultdict(list))

        reader = csv.reader(fileobj)
        for row in reader:
            row = list(filter(None, row))
            if header is None:
                assert HEADER == row, row
                header = row
                continue

            row = {h: d for h, d in zip(header, row)}
            try:
                entry = self.process_row(row)
            except Exception as e:
                result['errors'][e.__class__.__name__].append((e, row))
            else:
                result['entries'].append(entry)

        return result


if __name__ == '__main__':
    parser = ExpenseCSVParser()
    filename = sys.argv[1]
    with open(filename) as f:
        result = parser.parse(fileobj=f)
    if result['errors']:
        print(
            [(k, v) for k, v in result['errors'].items()]
        )
