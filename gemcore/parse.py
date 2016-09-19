# /usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import os
import re
import sys

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from collections import namedtuple
from django.contrib.auth.models import User
from gemcore.forms import EntryForm
from gemcore.models import Account, Book


UserData = namedtuple('UserData', ['user', 'account'])


class RowToBeProcessesError(Exception):
    """This row will be processed later."""


class CSVParser(object):

    DATE_FORMAT = '%Y-%m-%d'
    AMOUNT_FIELDS = []
    WHEN = None
    WHAT = None
    HEADER = []
    IGNORE_ROWS = 0

    def __init__(self, book, users):
        super(CSVParser, self).__init__()
        self.book = book
        self.users = users
        self.name = None
        self.header = None

    def find_header(self, row):
        assert self.HEADER == row, (
            'The header %s is not the expected %s' % (row, self.HEADER))
        return row

    def find_amount(self, row):
        amount = None
        for field in self.AMOUNT_FIELDS:
            amount = row.get(field, '')
            if amount:
                amount = re.sub(r'[^\d\-.]', '', self.process_amount(amount))
                break
        return amount

    def process_amount(self, value):
        """Implement on child."""
        return value

    def process_when(self, value):
        if self.DATE_FORMAT:
            value = datetime.strptime(value, self.DATE_FORMAT)
        return value

    def process_row(self, row):
        assert row, 'The given row is empty'
        when = None
        if self.WHEN in row:
            when = self.process_when(row[self.WHEN])

        amount = self.find_amount(row)
        assert amount, ('Amount not found: %r' % row)

        amount = Decimal(amount)
        return dict(
            when=when,
            what=row[self.WHAT],
            amount=abs(amount),
            is_income=amount > 0,
        )

    def process_data(self, data, dry_run=False):
        if not data:
            return None
        form = EntryForm(book=self.book, data=data)
        if not form.is_valid():
            msg = ' | '.join(
                '%s: %s' % (k, ', '.join(v)) for k, v in form.errors.items())
            raise ValueError(msg)
        entry = None
        if not dry_run:
            entry = form.save(book=self.book)

        return entry

    def parse(self, fileobj, dry_run=False):
        self.name = fileobj.name
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

            if self.header is None:
                self.header = self.find_header(row)
                continue

            row = {h: d for h, d in zip(self.header, row)}
            if not row:
                continue

            try:
                data = self.process_row(row)
                entry = self.process_data(data, dry_run=dry_run)
            except RowToBeProcessesError:
                continue
            except Exception as e:
                result['errors'][e.__class__.__name__].append((e, row))
            else:
                result['entries'].append(entry)

        return result


class ExpenseCSVParser(CSVParser):

    AMOUNT_FIELDS = ['How much']
    WHAT = 'Why'
    WHEN = 'When'
    WHO = 'Who'
    TAG = 'What'
    HEADER = [
        WHEN, WHO, WHAT, TAG, 'How much', 'Summary category', 'Summary amount']
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

    def __init__(self, book, users=None):
        if users is None:
            matiasb = UserData(
                user=User.objects.get(username='matiasb'),
                account=Account.objects.get(slug='cash-ars-matiasb'))
            nessita = UserData(
                user=User.objects.get(username='nessita'),
                account=Account.objects.get(slug='cash-ars-nessita'))
            users = {'M': matiasb, 'N': nessita}
        super(ExpenseCSVParser, self).__init__(book=book, users=users)

    def process_row(self, row):
        row = super(ExpenseCSVParser, self).process_row(row)
        userdata = self.users[row[self.WHO]]
        data = dict(
            who=userdata.user.id,
            account=userdata.account.id,
            country='AR',
            tags=self.TAGS_MAPPING[row[self.WHAT]],
        )
        return data


class ScoBankCSVParser(CSVParser):

    AMOUNT_FIELDS = ['Débito', 'Crédito']
    COMMENTS = ['﻿"Suc."', "Fecha Valor", "Comprobante", "Saldo"]
    DATE_FORMAT = '%d/%m/%Y'
    WHAT = 'Descripción'
    WHEN = 'Fecha'
    HEADER = ['﻿"Suc."', "Fecha", "Fecha Valor", "Descripción", "Comprobante",
              "Débito", "Crédito", "Saldo"]

    def __init__(self, book, users=None):
        if users is None:
            user = User.objects.get(username='nessita')
            account = Account.objects.get(slug='sco-dim-usd-shared')
            users = UserData(user=user, account=account)
        super(ScoBankCSVParser, self).__init__(book=book, users=users)
        self.extra = defaultdict(dict)

    def process_amount(self, value):
        return value.replace('.', '').replace(',', '.')

    def process_row(self, row):
        data = super(ScoBankCSVParser, self).process_row(row)
        notes = ' | '.join('%s: %s' % (k.strip('\ufeff').strip('"'), row[k])
                           for k in self.COMMENTS)
        data.update(dict(
            who=self.users.user.id,
            notes=notes,
            account=self.users.account.id,
            country='UY',
            tags=['imported'],
        ))
        return data


class WFGBankCSVParser(CSVParser):

    AMOUNT_FIELDS = ['How Much']
    DATE_FORMAT = '%m/%d/%Y'
    WHEN = 0
    WHAT = 4
    HEADER = None
    EXTRA_FEES = (
        'INTERNATIONAL PURCHASE TRANSACTION FEE',
        'NON-WELLS FARGO ATM TRANSACTION FEE',
    )

    def __init__(self, book, users=None):
        if users is None:
            user = User.objects.get(username='matiasb')
            account = Account.objects.get(slug='wfg-usd-matiasb')
            users = UserData(user=user, account=account)
        super(WFGBankCSVParser, self).__init__(book=book, users=users)
        self.last_extra_fee = None
        self.header = [
            self.WHEN, self.AMOUNT_FIELDS[0], 'i-1', 'i-2', self.WHAT]

    def find_header(self, row):
        # csv comes with no header, fake one
        raise NotImplementedEror()

    def process_row(self, row):
        data = super(WFGBankCSVParser, self).process_row(row)
        data.update(dict(
            who=self.users.user.id,
            account=self.users.account.id,
            country='US',
            tags=['imported'],
        ))
        if data['what'] in self.EXTRA_FEES:
            assert self.last_extra_fee is None
            self.last_extra_fee = data
            raise RowToBeProcessesError()

        if self.last_extra_fee is not None:
            assert self.last_extra_fee['is_income'] == data['is_income']
            assert self.last_extra_fee['when'] == data['when']
            amount = self.last_extra_fee['amount']
            data['notes'] = '%s + %s %s' % (
                data['amount'], self.last_extra_fee['what'], amount)
            data['amount'] += amount
            self.last_extra_fee = None

        return data


class TripCSVParser(CSVParser):

    COUNTRY = 'Country'
    WHAT = 'What'
    WHEN = 'When'
    WHO = 'Who'
    HEADER = [WHEN, WHO, WHAT, COUNTRY]
    IGNORE_ROWS = 4

    def __init__(self, book, users=None):
        matiasb = User.objects.get(username='matiasb')
        nessita = User.objects.get(username='nessita')
        users = {
            'ARS': {
                'M': UserData(
                    user=matiasb,
                    account=Account.objects.get(slug='cash-ars-matiasb')),
                'N': UserData(
                    user=nessita,
                    account=Account.objects.get(slug='cash-ars-nessita')),
                'X': UserData(
                    user=nessita,
                    account=Account.objects.get(slug='cash-ars-shared')),
            },
            'BRL': {
                'M': UserData(
                    user=matiasb,
                    account=Account.objects.get(slug='cash-brl-shared')),
                'N': UserData(
                    user=nessita,
                    account=Account.objects.get(slug='cash-brl-shared')),
            },
            'UYU': {
                'X': UserData(
                    user=nessita,
                    account=Account.objects.get(slug='cash-uyu-shared')),
                'N': UserData(
                    user=nessita,
                    account=Account.objects.get(slug='cash-uyu-shared')),
                'M': UserData(
                    user=matiasb,
                    account=Account.objects.get(slug='cash-uyu-shared')),
            },
            'USD': {
                'M': UserData(
                    user=matiasb,
                    account=Account.objects.get(slug='cash-usd-matiasb')),
                'N': UserData(
                    user=nessita,
                    account=Account.objects.get(slug='cash-usd-nessita')),
                'X': UserData(
                    user=nessita,
                    account=Account.objects.get(slug='cash-usd-shared')),
            },
            'EUR': {
                'M': UserData(
                    user=matiasb,
                    account=Account.objects.get(slug='cash-eur-matiasb')),
                'N': UserData(
                    user=nessita,
                    account=Account.objects.get(slug='cash-eur-nessita')),
                'X': UserData(
                    user=nessita,
                    account=Account.objects.get(slug='cash-eur-shared')),
            },
        }
        super(TripCSVParser, self).__init__(book=book, users=users)
        self.currencies = None

    def find_header(self, row):
        header_len = len(self.HEADER)
        assert self.HEADER == row[:header_len], (
            'The header %s is not the expected %s' % (row, self.HEADER))
        self.currencies = row[header_len:]
        return row

    def process_row(self, row):
        data = super(TripCSVParser, self).process_row(row)
        amount = None
        currency = None
        for c in self.currencies:
            if row[c]:
                amount = Decimal(self.process_amount(row[c]))
                currency = c
                break

        assert amount is not None

        userdata = self.users[currency][row[self.WHO]]
        data.update(dict(
            amount=amount,
            who=userdata.user.id,
            notes=self.name,
            account=userdata.account.id,
            country=row[self.COUNTRY],
            tags=['trips'],
        ))
        return data


PARSER_MAPPING = {
    'sco-bank': ScoBankCSVParser,
    'wfg-bank': WFGBankCSVParser,
    'trips': TripCSVParser,
    'expense': ExpenseCSVParser,
}
