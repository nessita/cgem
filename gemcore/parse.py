# /usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import re

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from collections import namedtuple
from gemcore.forms import EntryForm


UserData = namedtuple('UserData', ['user', 'account'])


class RowToBeProcessesError(Exception):
    """This row will be processed later."""


class CSVParser(object):

    AMOUNTS = []
    NOTES = []
    WHEN = None
    WHAT = None

    COUNTRY = None
    DATE_FORMAT = '%Y-%m-%d'
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
        result = None
        for field in self.AMOUNTS:
            result = row.get(field, '')
            if result:
                result = re.sub(r'[^\d\-.]', '', self.process_amount(result))
                break
        assert result, (
            'Amount not found (tried %r): %r' % (self.AMOUNTS, row))
        return Decimal(result)

    def find_notes(self, row):
        notes = ' | '.join(
            '%s: %s' % (k.strip('\ufeff').strip('"'), row[k])
            for k in self.NOTES)
        return notes

    def find_tags(self, row, account):
        tags = account.tags_for(row[self.WHAT]).keys() or ['imported']
        return tags

    def find_when(self, row):
        when = None
        if self.WHEN in row:
            when = self.process_when(row[self.WHEN])
        assert when, ('When not found (tried %r): %r' % (self.WHEN, row))
        return when

    def process_amount(self, value):
        """Implement on child."""
        return value

    def process_when(self, value):
        if self.DATE_FORMAT:
            value = datetime.strptime(value, self.DATE_FORMAT)
        return value

    def process_row(self, row, user, account, unprocessed_rows=None):
        assert row, 'The given row is empty'
        amount = self.find_amount(row)
        return dict(
            account=account.id, amount=abs(amount), country=self.COUNTRY,
            is_income=amount > 0, notes=self.find_notes(row),
            tags=self.find_tags(row, account), what=row[self.WHAT],
            when=self.find_when(row), who=user.id)

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
                # Needs a transfer?
                tags = account.tags_for(data['what'])
                for transfer in filter(None, tags.values()):
                    data['is_income'] = not data['is_income']
                    data['account'] = transfer.id
                    self.make_entry(result, data, book, dry_run=dry_run)

        return result


class ExpenseCSVParser(CSVParser):

    AMOUNTS = ['How much']
    NOTES = ['Summary category', 'Summary amount']
    WHAT = 'Why'
    WHEN = 'When'
    WHO = 'Who'
    TAG = 'What'
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

    COUNTRY = 'AR'
    HEADER = [WHEN, WHO, WHAT, TAG] + AMOUNTS + NOTES

    def find_tags(self, row, account):
        return self.TAGS_MAPPING[row[self.WHAT]]


class ScoBankCSVParser(CSVParser):

    AMOUNTS = ['Débito', 'Crédito']
    NOTES = ['﻿"Suc."', "Fecha Valor", "Comprobante", "Saldo"]
    WHAT = 'Descripción'
    WHEN = 'Fecha'

    COUNTRY = 'UY'
    DATE_FORMAT = '%d/%m/%Y'
    HEADER = ['﻿"Suc."', "Fecha", "Fecha Valor", "Descripción", "Comprobante",
              "Débito", "Crédito", "Saldo"]

    def process_amount(self, value):
        return value.replace('.', '').replace(',', '.')


class WFGBankCSVParser(CSVParser):

    AMOUNTS = ['How Much']
    WHEN = 0
    WHAT = 4

    COUNTRY = 'US'
    DATE_FORMAT = '%m/%d/%Y'
    EXTRA_FEES = (
        'INTERNATIONAL PURCHASE TRANSACTION FEE',
        'NON-WELLS FARGO ATM TRANSACTION FEE')
    HEADER = None

    @property
    def header(self):
        return [self.WHEN, self.AMOUNTS[0], 'i-1', 'i-2', self.WHAT]

    def find_header(self, row):
        # csv comes with no header, fake one
        raise NotImplementedError()

    def process_row(self, row, unprocessed_rows, **kwargs):
        data = super(WFGBankCSVParser, self).process_row(row, **kwargs)
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

    AMOUNTS = ['Débito', 'Crédito']
    NOTES = ['Número Documento', 'Num. Dep.', 'Asunto']
    WHEN = 'Fecha'
    WHAT = 'Descripción'

    COUNTRY = 'UY'
    DATE_FORMAT = '%d/%m/%Y'
    HEADER = ['', WHEN, '', WHAT] + NOTES + [''] + AMOUNTS
    IGNORE_ROWS = 5

    def process_row(self, row, **kwargs):
        data = super(BrouBankParser, self).process_row(row, **kwargs)
        data['is_income'] = False if row['Débito'] else True
        return data


class BNABankParser(CSVParser):

    AMOUNTS = ['Importe']
    NOTES = ['Comentarios', 'Saldo Parcial']
    WHEN = 'Fecha / Hora Mov.'
    WHAT = 'Concepto'

    DATE_FORMAT = '%d/%m/%Y'
    COUNTRY = 'AR'
    HEADER = [WHEN, WHAT] + AMOUNTS + NOTES


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
        for c in self.currencies:
            if row[c]:
                amount = Decimal(self.process_amount(row[c]))
                break

        assert amount is not None

        data['amount'] = amount
        data['notes'] = self.name
        data['country'] = row[self.COUNTRY]
        data['tags'].append('trips')

        return data
