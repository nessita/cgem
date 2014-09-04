# /usr/bin/env python3

import csv
import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gem.settings')

from datetime import datetime
from decimal import Decimal

import django
django.setup()

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
HEADER = [
    WHEN, WHO, WHY, WHAT, AMOUNT,
    'Summary category', 'Summary amount']


class ExpenseCSVParser(object):

    def __init__(self, filename):
        super(ExpenseCSVParser, self).__init__()
        matiasb = UserData(
            user=User.objects.get(username='matiasb'),
            account=Account.objects.get(slug='cash-ars-matiasb'))
        nessita = UserData(
            user=User.objects.get(username='nessita'),
            account=Account.objects.get(slug='cash-ars-nessita'))
        self.users = {'M': matiasb, 'N': nessita}
        self.book = Book.objects.get(slug='our-expenses')
        self.filename = filename

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
            tags=CATEGORY_MAPPING[row[WHAT]],
        )
        form = EntryForm(data=data)
        assert form.is_valid(), form.errors
        try:
            entry = form.save(book=self.book)
        except IntegrityError:
            entry = None
        return entry

    def parse(self):
        header = None
        result = 0
        with open(self.filename) as f:
            reader = csv.reader(f)
            for row in reader:
                row = list(filter(None, row))
                if header is None:
                    assert HEADER == row, row
                    header = row
                    continue

                row = {h: d for h, d in zip(header, row)}
                entry = self.process_row(row)
                if entry is not None:
                    result += 1
                else:
                    print('ERROR: could not create entry for %s' % row)


parser = ExpenseCSVParser(
    filename='/home/nessita/Documents/expenses-08-2010.csv')
parser.parse()
