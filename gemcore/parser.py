# /usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import re

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from django.db import transaction

from gemcore.forms import EntryForm


class DataToBeProcessedError(Exception):
    """This row will be processed later."""

    def __init__(self, data, *args, **kwargs):
        self.data = data
        super(DataToBeProcessedError, self).__init__(*args, **kwargs)


class CSVParser(object):

    def __init__(self, account):
        super(CSVParser, self).__init__()
        self.account = account
        self.config = self.account.parser_config

    def _parse_amount(self, row, i):
        result = '0'
        value = row[i]
        if value:
            value = value.replace(self.config.thousands_sep, '')
            if self.config.decimal_point != '.':
                value = value.replace(self.config.decimal_point, '.')
            result = re.sub(r'[^\d\-.]', '', value)

        try:
            result = Decimal(result)
        except Exception as e:
            assert False, (
                'Can not convert %r to Decimal (got it from row %s, index %s)'
                % (result, row, i))

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
        notes = ([row[k] for k in self.config.notes if row[k]] +
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
        assert row, 'The given row %r is empty' % row
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

    def _validate_and_save_entry(self, data, book, dry_run=False):
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

    @transaction.atomic
    def make_entry(self, data, book, dry_run=False):
        if not data:
            return None
        entry = self._validate_and_save_entry(data, book, dry_run=dry_run)

        # Needs a transfer?
        tags = self.account.tags_for(data['what'])
        for transfer in filter(None, tags.values()):
            data['is_income'] = not data['is_income']
            data['account'] = transfer.id
            self._validate_and_save_entry(data, book, dry_run=dry_run)

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

        return result
