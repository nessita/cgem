# /usr/bin/env python3
# -*- coding: utf-8 -*-

import codecs
import csv
import logging
import re
from copy import copy
from datetime import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError

from gemcore.forms import create_entry

logger = logging.getLogger(__name__)


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
        result = "0"
        value = row[i]
        if value:
            value = value.replace(self.config.thousands_sep, "")
            if self.config.decimal_point != ".":
                value = value.replace(self.config.decimal_point, ".")
            result = re.sub(r"[^\d\-.]", "", value)

        try:
            result = Decimal(result)
        except Exception:
            assert False, (
                "Can not convert %r to Decimal (got it from row %s, index %s)"
                % (result, row, i)
            )

        return result

    def find_amount(self, row):
        if len(self.config.amount) == 1:
            result = self._parse_amount(row, self.config.amount[0])
        else:
            assert len(self.config.amount) == 2, (
                "Config amount can not be bigger than 2 elements (got %r)."
                % self.config.amount
            )
            expense = self._parse_amount(row, self.config.amount[0])
            income = self._parse_amount(row, self.config.amount[1])
            result = income - abs(expense)
        return result

    def _concat_columns(self, row, indexes, extra=None):
        result = [row[i].strip() for i in indexes if row[i].strip()]
        return " | ".join(result + (extra or []))

    def find_notes(self, row):
        return self._concat_columns(
            row, self.config.notes, ["source: %r" % self.name]
        )

    def find_what(self, row):
        result = self._concat_columns(row, self.config.what)
        assert result, "What not found (tried %r): %r" % (
            self.config.what,
            row,
        )
        return result

    def find_when(self, row):
        result = None
        for i in self.config.when:
            result = row[i]
            if result:
                result = datetime.strptime(
                    result, self.config.date_format
                ).date()
                break
        assert result, "When not found (tried %r): %r" % (
            self.config.when,
            row,
        )
        return result

    def make_data(self, row, user, unprocessed=None):
        assert row, "The given row %r is empty" % row
        amount = self.find_amount(row)
        what = self.find_what(row)

        data = dict(
            account=self.account.id,
            amount=abs(amount),
            country=self.config.country,
            is_income=amount > 0,
            notes=self.find_notes(row),
            what=what,
            when=self.find_when(row),
            who=user.id,
        )
        if what in self.config.defer_processing:
            raise DataToBeProcessedError(data)

        data, _ = self._entry_account.resolve_entry_tagregexes(data)
        if data["asset"] is not None:
            data["asset"] = data["asset"].pk

        if unprocessed:
            assert unprocessed["is_income"] == data["is_income"]
            assert unprocessed["when"] == data["when"]
            amount = unprocessed["amount"]
            data["notes"] = "%s + %s %s" % (
                data["amount"],
                unprocessed["what"],
                amount,
            )
            data["amount"] += amount

        return data

    def make_entry(self, data, book, dry_run=False):
        entry_data = {**data, "account": self._entry_account, "book": book}
        try:
            return create_entry(dry_run=dry_run, **entry_data)
        except ValidationError as error:
            errors = (
                error.message_dict
                if hasattr(error, "message_dict")
                else {"__all__": error.messages}
            )
            message = " | ".join(
                f"{field}: {', '.join(messages)}"
                for field, messages in errors.items()
            )
            raise ValueError(message) from error

    def add_error(self, result, error, data):
        error = {
            "exception": error.__class__.__name__,
            "message": str(error),
            "data": data,
        }
        result["errors"].append(error)

    def parse(self, fileobj, book, user, dry_run=False):
        # A later import must see tag regex edits on an unprefetched account.
        self._entry_account = copy(self.account).prefetch_tagregexes()
        self.name = getattr(fileobj, "name", "stream with no name")
        result = dict(entries=[], errors=[])

        delimiter = codecs.decode(self.config.delimiter, "unicode_escape")
        reader = csv.reader(fileobj, delimiter=delimiter)
        ignored = 0
        unprocessed = None
        for row in reader:
            # ignore initial rows
            if ignored < self.config.ignore_rows:
                logger.info(
                    "CSVParser.parse ignoring row %i: %r", ignored, row
                )
                ignored += 1
                continue

            if not row or not any(row):
                continue

            try:
                data = self.make_data(
                    row=row, user=user, unprocessed=unprocessed
                )
            except DataToBeProcessedError as e:
                assert (
                    unprocessed is None
                ), f"Unprocessed data should be None, got {unprocessed=}"
                unprocessed = e.data
                continue
            except Exception as e:
                self.add_error(result, e, row)
                continue

            if not data:
                return None

            unprocessed = None
            try:
                entry = self.make_entry(data, book=book, dry_run=dry_run)
            except Exception as e:
                self.add_error(result, e, data)
            else:
                assert entry is not None, "Entry should not be None"
                result["entries"].append(entry)

        return result
