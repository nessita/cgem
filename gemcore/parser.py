# /usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import re

from collections import defaultdict, namedtuple
from datetime import datetime
from decimal import Decimal

from django.db import transaction

from gemcore.forms import EntryForm


UserData = namedtuple('UserData', ['user', 'account'])


class DataToBeProcessedError(Exception):
    """This row will be processed later."""

    def __init__(self, data, *args, **kwargs):
        self.data = data
        super(DataToBeProcessedError, self).__init__(*args, **kwargs)


class OldParser(object):

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
                if ',' in result:  # .ar locale
                    result = result.replace('.', '').replace(',', '.')
                result = re.sub(r'[^\d\-.]', '', result)
                break
        assert result, (
            'Amount not found (tried %r): %r' % (self.AMOUNTS, row))
        return Decimal(result)

    def find_notes(self, row):
        notes = ['%s: %s' % (k.strip('\ufeff').strip('"'), row[k])
                 for k in self.NOTES] + ['source: %r' % self.name]
        return ' | '.join(notes)

    def find_tags(self, row, account):
        tags = list(account.tags_for(row[self.WHAT]).keys()) or ['imported']
        return tags

    def find_when(self, row):
        when = None
        if self.WHEN in row and self.DATE_FORMAT:
            when = datetime.strptime(row[self.WHEN], self.DATE_FORMAT)
        assert when, ('When not found (tried %r): %r' % (self.WHEN, row))
        return when

    def make_data(self, row, user, account, unprocessed=None):
        assert row, 'The given row is empty'
        amount = self.find_amount(row)
        return dict(
            account=account.id, amount=abs(amount), country=self.COUNTRY,
            is_income=amount > 0, notes=self.find_notes(row),
            tags=self.find_tags(row, account), what=row[self.WHAT].strip(),
            when=self.find_when(row), who=user.id)

    @transaction.atomic
    def make_entry(self, data, book, dry_run=False):
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

    def parse(self, fileobj, book, user, account, dry_run=False):
        self.name = fileobj.name
        result = dict(entries=[], errors=defaultdict(list))

        reader = csv.reader(fileobj)
        ignored = 0
        header = self.header
        unprocessed = None
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
                data = self.make_data(row=row, user=user, account=account,
                                      unprocessed=unprocessed)
            except DataToBeProcessedError as e:
                assert unprocessed is None, 'Unprocessed data should be None'
                unprocessed = e.data
                continue

            unprocessed = None
            error = None
            try:
                entry = self.make_entry(data, book=book, dry_run=dry_run)
            except Exception as e:
                error = e

            if error is not None:
                result['errors'][error.__class__.__name__].append(
                    (error, data))
            else:
                assert entry is not None, 'Entry should not be None'
                result['entries'].append(entry)
                # Needs a transfer?
                tags = account.tags_for(data['what'])
                for transfer in filter(None, tags.values()):
                    data['is_income'] = not data['is_income']
                    data['account'] = transfer.id
                    entry = self.make_entry(data, book, dry_run=dry_run)
                    result['entries'].append(entry)

        return result


class ExpenseParser(OldParser):

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
        'Transporte': ['transportation'],
        'Auto': ['car'],
    }

    COUNTRY = 'AR'
    HEADER = [WHEN, WHO, WHAT, TAG] + AMOUNTS + NOTES

    def find_tags(self, row, account):
        return self.TAGS_MAPPING[row[self.WHAT]]


class ScoBankParser(OldParser):

    AMOUNTS = ['Débito', 'Crédito']
    NOTES = ['﻿"Suc."', "Fecha Valor", "Comprobante", "Saldo"]
    WHAT = 'Descripción'
    WHEN = 'Fecha'

    COUNTRY = 'UY'
    DATE_FORMAT = '%d/%m/%Y'
    HEADER = ['﻿"Suc."', "Fecha", "Fecha Valor", "Descripción", "Comprobante",
              "Débito", "Crédito", "Saldo"]


class WFGBankParser(OldParser):

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

    def make_data(self, row, user, account, unprocessed=None):
        data = super(WFGBankParser, self).make_data(
            row=row, user=user, account=account)

        if data['what'] in self.EXTRA_FEES:
            raise DataToBeProcessedError(data)

        if unprocessed:
            assert unprocessed['is_income'] == data['is_income']
            assert unprocessed['when'] == data['when']
            amount = unprocessed['amount']
            data['notes'] = '%s + %s %s' % (
                data['amount'], unprocessed['what'], amount)
            data['amount'] += amount

        return data


class BrouBankParser(OldParser):

    AMOUNTS = ['Débito', 'Crédito']
    NOTES = ['Número Documento', 'Num. Dep.', 'Asunto']
    WHEN = 'Fecha'
    WHAT = 'Descripción'

    COUNTRY = 'UY'
    DATE_FORMAT = '%d/%m/%Y'
    HEADER = ['', WHEN, '', WHAT] + NOTES + [''] + AMOUNTS
    IGNORE_ROWS = 5

    def make_data(self, row, **kwargs):
        data = super(BrouBankParser, self).make_data(row, **kwargs)
        data['is_income'] = False if row['Débito'] else True
        return data


class BNABankParser(OldParser):

    AMOUNTS = ['Importe']
    NOTES = ['Comentarios', 'Saldo Parcial']
    WHEN = 'Fecha / Hora Mov.'
    WHAT = 'Concepto'

    DATE_FORMAT = '%d/%m/%Y'
    COUNTRY = 'AR'
    HEADER = [WHEN, WHAT] + AMOUNTS + NOTES


class TripParser(OldParser):

    COUNTRY = 'Country'
    WHAT = 'What'
    WHEN = 'When'
    WHO = 'Who'
    HEADER = [WHEN, WHO, WHAT, COUNTRY]
    IGNORE_ROWS = 4

    def __init__(self):
        super(TripParser, self).__init__()
        self.currencies = None

    def find_header(self, row):
        header_len = len(self.HEADER)
        assert self.HEADER == row[:header_len], (
            'The header %s is not the expected %s' % (row, self.HEADER))
        self.currencies = row[header_len:]
        return row

    def make_data(self, row, **kwargs):
        data = super(TripParser, self).make_data(row, **kwargs)
        amount = None
        for c in self.currencies:
            if row[c]:
                amount = Decimal(row[c])
                break

        assert amount is not None

        data['amount'] = amount
        data['notes'] = self.name
        data['country'] = row[self.COUNTRY]
        data['tags'].append('trips')

        return data


class CSVParser(object):

    def __init__(self, account):
        super(CSVParser, self).__init__()
        self.account = account
        self.config = self.account.parser_config

    def _parse_amount(self, row, i):
        result = Decimal(0)
        value = row[i]
        if value:
            value = value.replace(self.config.thousands_sep, '')
            if self.config.decimal_point != '.':
                value = value.replace(self.config.decimal_point, '.')
            result = Decimal(re.sub(r'[^\d\-.]', '', value))
        return result

    def find_amount(self, row):
        if len(self.config.amount) == 1:
            result = self._parse_amount(row, self.config.amount[0])
        else:
            assert len(self.config.amount) == 2, (
                'Config amount can not be bigger than 2 elements (got %r).' %
                self.config.amount)
            expense = self._parse_amount(row, self.config.amount[0])
            income = self._parse_amount(row, self.config.amount[1])
            result = income - abs(expense)
        return result

    def find_notes(self, row):
        notes = ([row[k] for k in self.config.notes] +
                 ['source: %r' % self.name])
        return ' | '.join(notes)

    def find_what(self, row):
        result = None
        for i in self.config.what:
            result = row[i].strip()
            if result:
                break
        assert result, ('What not found (tried %r): %r' %
                        (self.config.what, row))
        return result

    def find_when(self, row):
        result = None
        for i in self.config.when:
            result = row[i]
            if result:
                result = datetime.strptime(
                    result, self.config.date_format)
                break
        assert result, ('When not found (tried %r): %r' %
                        (self.config.when, row))
        return result

    def make_data(self, row, user, unprocessed=None):
        assert row, 'The given row is empty'
        amount = self.find_amount(row)
        what = self.find_what(row)
        tags = list(self.account.tags_for(what).keys()) or ['imported']
        data = dict(
            account=self.account.id, amount=abs(amount),
            country=self.config.country,
            is_income=amount > 0, notes=self.find_notes(row),
            tags=tags, what=what, when=self.find_when(row), who=user.id)

        if what in self.config.defer_processing:
            raise DataToBeProcessedError(data)

        if unprocessed:
            assert unprocessed['is_income'] == data['is_income']
            assert unprocessed['when'] == data['when']
            amount = unprocessed['amount']
            data['notes'] = '%s + %s %s' % (
                data['amount'], unprocessed['what'], amount)
            data['amount'] += amount

        return data

    @transaction.atomic
    def make_entry(self, data, book, dry_run=False):
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

    def parse(self, fileobj, book, user, dry_run=False):
        self.name = fileobj.name
        result = dict(entries=[], errors=defaultdict(list))

        reader = csv.reader(fileobj)
        ignored = 0
        unprocessed = None
        for row in reader:
            # ignore initial rows
            if ignored < self.config.ignore_rows:
                ignored += 1
                continue

            if not row or not any(row):
                continue

            try:
                data = self.make_data(
                    row=row, user=user, unprocessed=unprocessed)
            except DataToBeProcessedError as e:
                assert unprocessed is None, 'Unprocessed data should be None'
                unprocessed = e.data
                continue

            unprocessed = None
            error = None
            try:
                entry = self.make_entry(data, book=book, dry_run=dry_run)
            except Exception as e:
                error = e

            if error is not None:
                result['errors'][error.__class__.__name__].append(
                    (error, data))
            else:
                assert entry is not None, 'Entry should not be None'
                result['entries'].append(entry)
                # Needs a transfer?
                tags = self.account.tags_for(data['what'])
                for transfer in filter(None, tags.values()):
                    data['is_income'] = not data['is_income']
                    data['account'] = transfer.id
                    entry = self.make_entry(data, book, dry_run=dry_run)
                    result['entries'].append(entry)

        return result
