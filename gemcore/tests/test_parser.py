import csv
from datetime import date, datetime
from decimal import Decimal
from io import StringIO

from django.conf import settings

from gemcore.constants import TAGS
from gemcore.models import Account, Entry
from gemcore.parser import CSVParser
from gemcore.tests.helpers import BaseTestCase


class CSVParserTestCase(BaseTestCase):
    def make_account_with_parser(self, **kwargs):
        parser = self.factory.make_parser_config(**kwargs)
        user = self.factory.make_user()
        account = self.factory.make_account(users=[user], parser_config=parser)
        return account

    def do_parse(self, account, stream, book=None):
        user = account.users.get()
        if book is None:
            book = self.factory.make_book(users=[user])

        result = CSVParser(account).parse(stream, book=book, user=user)
        stream.seek(0)
        reader = csv.reader(stream)
        rows = [i for i in reader if filter(bool, i)]

        return result, rows

    def assert_result(self, result, errors, entries, all_entries=None):
        self.assertEqual(
            len(result["errors"]),
            errors,
            "Expected %r errors (got %s %s instead)."
            % (errors, len(result["errors"]), result["errors"]),
        )
        self.assertEqual(len(result["entries"]), entries)
        if all_entries is None:
            all_entries = entries
        self.assertEqual(Entry.objects.all().count(), all_entries)

    def assert_entry_correct(self, **kwargs):
        entries = Entry.objects.filter(**kwargs)
        self.assertEqual(entries.count(), 1)

    def test_duplicated_entry(self):
        account = self.make_account_with_parser(
            when=[0], what=[1], amount=[2, 3], country="US"
        )
        user = account.users.get()
        book = self.factory.make_book(users=[user])

        f = StringIO("2021-10-21,line 1,10,0\n" "2021-10-21,line 2,0,20\n")
        result, rows = self.do_parse(account, f, book)
        self.assert_result(result, errors=0, entries=2)

        f = StringIO("2021-10-21,line 2,0,20")
        result, rows = self.do_parse(account, f, book)

        self.assert_result(result, errors=1, entries=0, all_entries=2)
        data = {
            "account": account.pk,
            "asset": None,
            "amount": Decimal("20"),
            "country": "US",
            "is_income": True,
            "notes": "source: 'stream with no name'",
            "tags": [settings.ENTRY_TAGS["default"]],
            "what": "line 2",
            "when": date(2021, 10, 21),
            "who": user.pk,
        }
        error = {
            "exception": "ValueError",
            "message": "__all__: There is already an entry for this data.",
            "data": data,
        }
        self.assertEqual(result["errors"], [error])

    def test_index_error(self):
        account = self.make_account_with_parser(
            when=[0], what=[1], amount=[2, 3], country="ES"
        )

        f = StringIO(
            "2021-10-21,line 1,10,0\n"
            "hola mono\n"
            "2021-10-21,line 2,0,20\n"
            ""
        )
        result, rows = self.do_parse(account, f)

        self.assert_result(result, errors=1, entries=2)
        error = {
            "exception": "IndexError",
            "message": "list index out of range",
            "data": ["hola mono"],
        }
        self.assertEqual(result["errors"], [error])

    def test_conflicting_tagregexes_reject_only_the_affected_row(self):
        account = self.make_account_with_parser(
            when=[0], what=[1], amount=[2], country="US"
        )
        for tag in ("FD", "TR"):
            self.factory.make_tag_regex(
                regex="^Ambiguous", tag=tag, account=account
            )
        result, _ = self.do_parse(
            account,
            StringIO(
                "2026-11-01,Ambiguous entry,10\n" "2026-11-02,Valid entry,20\n"
            ),
        )
        self.assert_result(result, errors=1, entries=1)
        self.assertIn("exactly one tag", result["errors"][0]["message"])
        self.assertEqual(
            Entry.objects.get().tags, [settings.ENTRY_TAGS["default"]]
        )

    def test_malformed_stored_tagregex_is_reported_for_each_csv_row(self):
        account = self.make_account_with_parser(
            when=[0], what=[1], amount=[2], country="US"
        )
        user = account.users.get()
        book = self.factory.make_book(users=[user])
        target = self.factory.make_account(users=[user])
        account.tagregex_set.create(regex=".*", tag=TAGS[0], transfer=target)
        tagregex = account.tagregex_set.create(
            regex="(?P=CONFIG_SECRET)", tag=TAGS[0]
        )
        parser = CSVParser(account)
        stream = StringIO(
            "2026-11-01,First entry,-10\n2026-11-02,Next entry,20\n"
        )
        result = parser.parse(stream, book=book, user=user)
        self.assert_result(result, errors=2, entries=0)
        self.assertEqual(
            [error["data"][1] for error in result["errors"]],
            ["First entry", "Next entry"],
        )
        for error in result["errors"]:
            self.assertEqual(error["exception"], "ValidationError")
            self.assertRegex(
                error["message"], r"Invalid tag regex at position \d+\."
            )
            self.assertNotIn("CONFIG_SECRET", error["message"])
        tagregex.regex = "^Never matches$"
        tagregex.save(update_fields=["regex"])
        stream.seek(0)
        result = parser.parse(stream, book=book, user=user)
        self.assert_result(result, errors=0, entries=2, all_entries=4)

    def test_deferred_fee_merges_without_resolving_its_tagregexes(self):
        account = self.make_account_with_parser(
            when=[0],
            what=[1],
            amount=[2],
            country="US",
            defer_processing=["Bank fee"],
        )
        for tag in TAGS[:2]:
            self.factory.make_tag_regex(
                regex="^Bank fee$", tag=tag, account=account
            )
        self.factory.make_tag_regex(
            regex="^Purchase$", tag=TAGS[2], account=account
        )
        result, _ = self.do_parse(
            account,
            StringIO("2026-11-01,Bank fee,-2\n2026-11-01,Purchase,-10\n"),
        )
        self.assert_result(result, errors=0, entries=1)
        entry = result["entries"][0]
        self.assertEqual(entry.what, "Purchase")
        self.assertEqual(entry.amount, Decimal("12"))
        self.assertIs(entry.is_income, False)
        self.assertEqual(entry.tags, [TAGS[2]])
        self.assertIn("Bank fee", entry.notes)

    def test_transfer_dry_run_does_not_save_or_mutate_source_data(self):
        account = self.make_account_with_parser(
            when=[0], what=[1], amount=[2], country="US"
        )
        user = account.users.get()
        book = self.factory.make_book(users=[user])
        target = self.factory.make_account(users=[user])
        account.tagregex_set.create(
            regex=".*", tag=settings.ENTRY_TAGS["transfer"], transfer=target
        )
        parser = CSVParser(account)
        stream = StringIO("2026-11-01,Transfer,-12.50\n")
        result = parser.parse(stream, book=book, user=user, dry_run=True)
        self.assert_result(result, errors=0, entries=1, all_entries=0)
        data = result["entries"][0]
        self.assertEqual(data["account"], account.pk)
        self.assertIs(data["is_income"], False)
        self.assertEqual(data["amount"], Decimal("12.50"))
        self.factory.make_entry(
            book=book,
            account=target,
            who=user,
            when=data["when"],
            what=data["what"],
            amount=data["amount"],
            is_income=True,
        )
        stream.seek(0)
        result = parser.parse(stream, book=book, user=user, dry_run=True)
        self.assert_result(result, errors=1, entries=0, all_entries=1)
        self.assertIn("already an entry", result["errors"][0]["message"])
        self.assertEqual(result["errors"][0]["data"]["account"], account.pk)

    def test_duplicate_transfer_rolls_back_source_and_continues_import(self):
        account = self.make_account_with_parser(
            when=[0], what=[1], amount=[2], country="US"
        )
        user = account.users.get()
        book = self.factory.make_book(users=[user])
        target = self.factory.make_account(users=[user])
        account.tagregex_set.create(
            regex="^Transfer",
            tag=settings.ENTRY_TAGS["transfer"],
            transfer=target,
        )
        self.factory.make_entry(
            book=book,
            account=target,
            who=user,
            when=date(2026, 11, 1),
            what="Transfer",
            amount=Decimal("12.50"),
            is_income=True,
        )
        result, _ = self.do_parse(
            account,
            StringIO(
                "2026-11-01,Transfer,-12.50\n2026-11-02,Another entry,20\n"
            ),
            book,
        )
        self.assert_result(result, errors=1, entries=1, all_entries=2)
        self.assertIn("already an entry", result["errors"][0]["message"])
        self.assertEqual(
            list(account.entry_set.values_list("what", flat=True)),
            ["Another entry"],
        )

    def test_tagregex_queries_do_not_grow_with_import_size(self):
        account = self.make_account_with_parser(
            when=[0], what=[1], amount=[2], country="US"
        )
        user = account.users.get()
        book = self.factory.make_book(users=[user])
        target = self.factory.make_account(users=[user])
        account.tagregex_set.create(
            regex=".*", tag=settings.ENTRY_TAGS["transfer"], transfer=target
        )
        for prefetched in (False, True):
            with self.subTest(prefetched=prefetched):
                source = account
                if prefetched:
                    source = Account.objects.prefetch_tagregexes().get(
                        pk=account.pk
                    )
                parser = CSVParser(source)
                items = [0]

                def execute():
                    prefix = f"2026-11-01,Transfer {prefetched}"
                    stream = StringIO(
                        "".join(
                            f"{prefix} {len(items)} {i},-12.50\n"
                            for i in items
                        )
                    )
                    return parser.parse(stream, book=book, user=user)

                with self.assertQueryCountUnchanged(
                    execute=execute,
                    make_more=lambda: items.extend(range(1, 8)),
                    query_filter=lambda query: (
                        'FROM "gemcore_tagregex"' in query["sql"]
                    ),
                ) as comparison:
                    for result, count in (
                        (comparison.before, 1),
                        (comparison.after, 8),
                    ):
                        self.assertEqual(result["errors"], [])
                        self.assertEqual(len(result["entries"]), count)
                    self.assertEqual(
                        comparison.before_count, 0 if prefetched else 1
                    )

    def test_tagregex_edits_are_seen_on_the_next_import(self):
        account = self.make_account_with_parser(
            when=[0], what=[1], amount=[2], country="US"
        )
        user = account.users.get()
        book = self.factory.make_book(users=[user])
        tags = [code for code, _ in settings.ENTRY_TAGS["choices"]][:2]
        tagregex = account.tagregex_set.create(regex=".*", tag=tags[0])
        parser = CSVParser(account)
        for tag in tags:
            tagregex.tag = tag
            tagregex.save(update_fields=["tag"])
            result = parser.parse(
                StringIO(f"2026-11-01,Entry {tag},12.50\n"),
                book=book,
                user=user,
            )
            self.assertEqual(result["errors"], [])
            self.assertEqual(result["entries"][0].tags, [tag])
            self.assertIs(hasattr(account, "prefetched_tagregexes"), False)

    def test_what_concatenates_columns(self):
        account = self.make_account_with_parser(
            when=[0], what=[2, 5, 4], amount=[1], country="ES"
        )
        f = StringIO(
            "2022-05-01,12,col 12, col 13, col 14, col 15,ignored\n"
            "2022-05-02,34,col 22, col 23, col 24, col 25,ignored\n"
            "2022-05-03,56,col 32, col 33, col 34, col 35,ignored\n"
            "2022-05-04,78,col 42, col 43, col 44, col 45,ignored\n"
            ""
        )
        result, rows = self.do_parse(account, f)

        self.assert_result(result, errors=0, entries=4)
        for i, entry in enumerate(result["entries"], start=1):
            self.assertEqual(entry.what, f"col {i}2 | col {i}5 | col {i}4")

    def test_parse_creates_entry_with_single_default_tag(self):
        account = self.make_account_with_parser(
            when=[0], what=[1], amount=[2, 3], country="US"
        )
        stream = StringIO("2021-10-21,line 1,10,0\n")

        result, rows = self.do_parse(account, stream)

        self.assert_result(result, errors=0, entries=1)
        self.assertEqual(
            result["entries"][0].tags, [settings.ENTRY_TAGS["default"]]
        )

    def test_bank1(self):
        # Fecha / Hora Mov.,Concepto,Importe,Comentarios,Saldo Parcial
        account = self.make_account_with_parser(
            when=[0],
            what=[1],
            amount=[2],
            notes=[3, 4],
            date_format="%d/%m/%Y",
            country="FR",
            ignore_rows=1,
        )

        fname = self.data_file("bank1.csv")
        with open(fname) as f:
            result, rows = self.do_parse(account, f)
        self.assert_result(result, errors=0, entries=225)

        # drop first row, header
        rows = rows[1:]
        for row in rows:
            row = [i for i in row if bool(i)]
            if not row or not any(row):
                continue
            when = datetime.strptime(row[0], account.parser_config.date_format)
            what = row[1].strip()
            amount = Decimal(row[2])
            is_income = amount > 0
            self.assert_entry_correct(
                account=account,
                country=account.parser_config.country,
                when=when,
                what=what,
                amount=abs(amount),
                is_income=is_income,
            )

    def test_bank2(self):
        # "Suc.","Fecha","Fecha Valor","Descripción","Comprobante",
        # "Débito","Crédito","Saldo"
        account = self.make_account_with_parser(
            when=[1, 2],
            what=[3],
            amount=[5, 6],
            notes=[0, 4, 7],
            date_format="%d/%m/%Y",
            country="ES",
            ignore_rows=1,
            thousands_sep=".",
            decimal_point=",",
        )

        fname = self.data_file("bank2.csv")
        with open(fname) as f:
            result, rows = self.do_parse(account, f)
        self.assert_result(result, errors=0, entries=78)

        # drop first row, header
        rows = rows[1:]
        for row in rows:
            if not row:
                continue
            when = datetime.strptime(row[1], "%d/%m/%Y")
            what = row[3]
            amount = row[5] if row[5] else row[6]
            amount = Decimal(amount.replace(".", "").replace(",", "."))
            is_income = amount > 0
            self.assert_entry_correct(
                account=account,
                country=account.parser_config.country,
                when=when,
                what=what,
                amount=abs(amount),
                is_income=is_income,
            )

    def test_bank3(self):
        # ,Fecha,,Descripción,Número Documento,Num. Dep.,Asunto,,Débito,Crédito
        account = self.make_account_with_parser(
            when=[1],
            what=[3],
            amount=[8, 9],
            notes=[4, 5, 6],
            date_format="%d/%m/%Y",
            country="IT",
            ignore_rows=6,
        )

        fname = self.data_file("bank3.csv")
        with open(fname) as f:
            result, rows = self.do_parse(account, f)
        self.assert_result(result, errors=0, entries=21)

        # drop dummy rows
        rows = rows[6:]
        for row in rows:
            if not row:
                continue
            when = datetime.strptime(row[1], "%d/%m/%Y")
            what = row[3].strip()
            if row[8]:
                amount = Decimal(row[8].replace(",", ""))
                is_income = False
            else:
                amount = Decimal(row[9].replace(",", ""))
                is_income = True
            self.assert_entry_correct(
                account=account,
                country=account.parser_config.country,
                when=when,
                what=what,
                amount=abs(amount),
                is_income=is_income,
            )

    def test_bank4(self):
        defer = [
            "INTERNATIONAL PURCHASE TRANSACTION FEE",
            "NON-WELLS FARGO ATM TRANSACTION FEE",
        ]
        account = self.make_account_with_parser(
            when=[0],
            what=[4],
            amount=[1],
            date_format="%m/%d/%Y",
            country="NZ",
            defer_processing=defer,
            ignore_rows=0,
        )

        fname = self.data_file("bank4.csv")
        with open(fname) as f:
            result, rows = self.do_parse(account, f)
        self.assert_result(result, errors=0, entries=54)

        last_extra_fee = 0
        for row in rows:
            if not row:
                continue
            when = datetime.strptime(row[0], "%m/%d/%Y")
            what = row[4]
            amount = Decimal(row[1])
            is_income = amount > 0
            if what in defer:
                last_extra_fee = amount
                continue

            amount = abs(amount) + abs(last_extra_fee)
            self.assert_entry_correct(
                account=account,
                country=account.parser_config.country,
                when=when,
                what=what,
                is_income=is_income,
                amount=amount,
            )
            last_extra_fee = 0
