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

    @property
    def header(self):
        return None

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

    def process_row(self, row, user, account, unprocessed_rows=None):
        assert row, 'The given row is empty'
        when = None
        if self.WHEN in row:
            when = self.process_when(row[self.WHEN])

        amount = self.find_amount(row)
        assert amount, ('Amount not found: %r' % row)

        amount = Decimal(amount)
        what = row[self.WHAT]
        tags = account.tags_for(what).keys() or ['imported']
        return dict(
            account=account.id,
            who=user.id,
            when=when,
            what=what,
            amount=abs(amount),
            is_income=amount > 0,
            tags=tags,
        )

    def process_data(self, data, book, dry_run=False):
        if not data:
            return None
        form = EntryForm(book=book, data=data)
        if not form.is_valid():
            msg = ' | '.join(
                '%s: %s' % (k, ', '.join(v)) for k, v in form.errors.items())
            raise ValueError(msg)
        if dry_run:
            entry = data
        else:
            entry = form.save(book=book)
        return entry

    def make_entry(self, result, data, book, dry_run=False):
        error = None
        try:
            entry = self.process_data(data, book=book, dry_run=dry_run)
        except Exception as e:
            error = e
            result['errors'][e.__class__.__name__].append((e, data))
        else:
            result['entries'].append(entry)
        return error

    def parse(self, fileobj, book, user, account, dry_run=False):
        self.name = fileobj.name
        result = dict(entries=[], errors=defaultdict(list))

        reader = csv.reader(fileobj)
        ignored = 0
        header = self.header
        unprocessed_rows = []
        for row in reader:
            # ignore initial rows
            if ignored < self.IGNORE_ROWS:
                ignored += 1
                continue

            # ignore empty values at the end
            while row and not row[-1]:
                row.pop()

            if header is None:
                header = self.find_header(row)
                continue

            row = {h: d for h, d in zip(header, row)}
            if not row:
                continue

            try:
                data = self.process_row(
                    row=row, unprocessed_rows=unprocessed_rows,
                    user=user, account=account)
            except RowToBeProcessesError:
                continue

            error = self.make_entry(result, data, book=book, dry_run=dry_run)
            if error is None:
                tags = account.tags_for(data['what'])
                for transfer in filter(None, tags.values()):
                    data['is_income'] = not data['is_income']
                    data['account'] = transfer.id
                    # Needs a transfer?
                    self.make_entry(result, data, book, dry_run=dry_run)

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

    def process_row(self, row, **kwargs):
        data = super(ExpenseCSVParser, self).process_row(row, **kwargs)
        data['country'] = 'AR'
        data['tags'].append(self.TAGS_MAPPING[row[self.WHAT]])
        return data


class ScoBankCSVParser(CSVParser):

    AMOUNT_FIELDS = ['Débito', 'Crédito']
    COMMENTS = ['﻿"Suc."', "Fecha Valor", "Comprobante", "Saldo"]
    DATE_FORMAT = '%d/%m/%Y'
    WHAT = 'Descripción'
    WHEN = 'Fecha'
    HEADER = ['﻿"Suc."', "Fecha", "Fecha Valor", "Descripción", "Comprobante",
              "Débito", "Crédito", "Saldo"]

    def process_amount(self, value):
        return value.replace('.', '').replace(',', '.')

    def process_row(self, row, **kwargs):
        data = super(ScoBankCSVParser, self).process_row(row, **kwargs)
        notes = ' | '.join('%s: %s' % (k.strip('\ufeff').strip('"'), row[k])
                           for k in self.COMMENTS)
        data.update(dict(
            notes=notes,
            country='UY',
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

    @property
    def header(self):
        return [self.WHEN, self.AMOUNT_FIELDS[0], 'i-1', 'i-2', self.WHAT]

    def find_header(self, row):
        # csv comes with no header, fake one
        raise NotImplementedEror()

    def process_row(self, row, unprocessed_rows, **kwargs):
        data = super(WFGBankCSVParser, self).process_row(row, **kwargs)
        data['country'] = 'US'
        if data['what'] in self.EXTRA_FEES:
            assert len(unprocessed_rows) == 0
            unprocessed_rows.append(data)
            raise RowToBeProcessesError()

        if unprocessed_rows:
            last_row = unprocessed_rows.pop()
            assert last_row['is_income'] == data['is_income']
            assert last_row['when'] == data['when']
            amount = last_row['amount']
            data['notes'] = '%s + %s %s' % (
                data['amount'], last_row['what'], amount)
            data['amount'] += amount

        return data


class BrouBankParser(CSVParser):

    DATE_FORMAT = '%d/%m/%Y'
    AMOUNT_FIELDS = ['Débito', 'Crédito']
    COMMENTS = ['Número Documento', 'Num. Dep.', 'Asunto']
    WHEN = 'Fecha'
    WHAT = 'Descripción'
    HEADER = [
        '', 'Fecha', '', 'Descripción', 'Número Documento', 'Num. Dep.',
        'Asunto', '', 'Débito', 'Crédito']
    IGNORE_ROWS = 5

    def process_row(self, row, **kwargs):
        data = super(BrouBankParser, self).process_row(row, **kwargs)
        is_income = False if row['Débito'] else True
        notes = ' | '.join('%s: %s' % (k, row[k]) for k in self.COMMENTS)
        data.update(dict(
            notes=notes,
            country='UY',
            is_income=is_income,
        ))
        return data


class TripCSVParser(CSVParser):

    COUNTRY = 'Country'
    WHAT = 'What'
    WHEN = 'When'
    WHO = 'Who'
    HEADER = [WHEN, WHO, WHAT, COUNTRY]
    IGNORE_ROWS = 4

    def __init__(self):
        super(TripCSVParser, self).__init__()
        self.currencies = None

    def find_header(self, row):
        header_len = len(self.HEADER)
        assert self.HEADER == row[:header_len], (
            'The header %s is not the expected %s' % (row, self.HEADER))
        self.currencies = row[header_len:]
        return row

    def process_row(self, row, **kwargs):
        data = super(TripCSVParser, self).process_row(row, **kwargs)
        amount = None
        currency = None
        for c in self.currencies:
            if row[c]:
                amount = Decimal(self.process_amount(row[c]))
                currency = c
                break

        assert amount is not None

        data['amount'] =  amount
        data['notes'] = self.name
        data['country'] = row[self.COUNTRY]
        data['tags'].append('trips')

        return data


PARSER_MAPPING = {i.__name__: i for i in (
    ExpenseCSVParser, ScoBankCSVParser, WFGBankCSVParser, BrouBankParser,
    TripCSVParser)}
