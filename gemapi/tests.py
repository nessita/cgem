import os
import random
import runpy
from contextlib import redirect_stdout
from datetime import date
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.test import override_settings
from django.urls import reverse

from gemcore.constants import TAGS, ChoicesMixin
from gemcore.models import Account, Entry
from gemcore.tests.helpers import BaseTestCase


class EntriesViewTestCase(BaseTestCase):
    url = reverse("api:entry-list")

    def book_url(self, slug):
        return reverse("api:book-entry-list", args=[slug])

    def make_auth_header(self, user=None):
        token = self.factory.make_token(user=user)
        self.api_user = token.user
        return {"HTTP_AUTHORIZATION": "Token " + token.key}

    def make_entry_data(self, book_slug=None, account_slug=None, **kwargs):
        if book_slug is None:
            book_slug = self.factory.make_book(users=[self.api_user]).slug
        if account_slug is None:
            account_slug = self.factory.make_account(
                users=[self.api_user]
            ).slug
        data = {
            "book": book_slug,
            "account": account_slug,
            "what": "One Test",
            "amount": "555.56",
            "tags": [settings.ENTRY_TAGS["default"]],
            "country": "US",
        }
        data.update(kwargs)
        return data

    def test_authentication_required(self):
        for url in (self.url, self.book_url("any-book")):
            for method in ("GET", "OPTIONS", "PATCH", "POST", "PUT", "DELETE"):
                with self.subTest(url=url, method=method):
                    response = getattr(self.client, method.lower())(url)
                    self.assertEqual(response.status_code, 401)

    def test_method_not_allowed(self):
        auth = self.make_auth_header()
        for method in ("PATCH", "PUT", "DELETE"):
            with self.subTest(method=method):
                response = getattr(self.client, method.lower())(
                    self.url, **auth
                )
                self.assertEqual(response.status_code, 405)

    def test_success(self):
        self.factory.make_book(slug="test-book")
        self.factory.make_account(slug="test-account")
        user = self.factory.make_user(username="test-user")
        auth = self.make_auth_header(user=user)
        data = self.make_entry_data()

        response = self.client.post(self.url, data=data, **auth)
        self.assertEqual(response.status_code, 201, response.content)

        entry = Entry.objects.get()
        self.assertEqual(entry.book.slug, data["book"])
        self.assertEqual(entry.account.slug, data["account"])
        self.assertEqual(entry.who, user)
        self.assertEqual(entry.what, data["what"])
        self.assertEqual(entry.amount, Decimal(data["amount"]))
        self.assertEqual(entry.tags, data["tags"])
        self.assertEqual(entry.country, data["country"])

    def test_rejects_empty_or_multiple_tags(self):
        auth = self.make_auth_header()
        data = self.make_entry_data()
        for tags in ([], TAGS[:2], [TAGS[0], TAGS[0]]):
            with self.subTest(tags=tags):
                response = self.client.post(
                    self.url,
                    data={**data, "tags": tags},
                    content_type="application/json",
                    **auth,
                )
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn("tags", response.json())
        self.assertEqual(Entry.objects.count(), 0)

    def test_tags_default_value_if_tags_missing(self):
        user = self.factory.make_user()
        auth = self.make_auth_header(user=user)
        data = self.make_entry_data()
        data.pop("tags")

        response = self.client.post(self.url, data=data, **auth)
        self.assertEqual(response.status_code, 201, response.content)

        entry = Entry.objects.get()
        self.assertEqual(entry.tags, [settings.ENTRY_TAGS["default"]])

    def test_tags_by_code(self):
        user = self.factory.make_user()
        auth = self.make_auth_header(user=user)
        tags = [random.choice(TAGS)]
        data = self.make_entry_data(tags=tags)

        response = self.client.post(self.url, data=data, **auth)
        self.assertEqual(response.status_code, 201, response.content)

        entry = Entry.objects.get()
        self.assertCountEqual(entry.tags, tags)

    def test_tags_by_name(self):
        user = self.factory.make_user()
        auth = self.make_auth_header(user=user)
        tag, label = random.choice(ChoicesMixin.TAG_CHOICES)
        data = self.make_entry_data()
        for index, value in enumerate(
            (label.lower(), label.capitalize(), label, label.upper())
        ):
            with self.subTest(value=value):
                what = f"Tag case {index}"
                response = self.client.post(
                    self.url,
                    data={**data, "tags": [value], "what": what},
                    **auth,
                )
                self.assertEqual(response.status_code, 201, response.content)
                self.assertEqual(Entry.objects.get(what=what).tags, [tag])

    def test_book_access_for_get_and_post(self):
        auth = self.make_auth_header()
        private_book = self.factory.make_book()
        for method, slug in (
            ("get", private_book.slug),
            ("post", private_book.slug),
            ("get", "missing-book"),
            ("post", "missing-book"),
        ):
            with self.subTest(method=method, slug=slug):
                response = getattr(self.client, method)(
                    self.book_url(slug), **auth
                )
                self.assertEqual(response.status_code, 404)
        self.assertEqual(Entry.objects.count(), 0)

    def test_default_book_for_get_single_and_bulk_post(self):
        auth = self.make_auth_header()
        book = self.factory.make_book(users=[self.api_user], default=True)
        other = self.factory.make_book(users=[self.api_user])
        data = self.make_entry_data(book_slug=book.slug)
        data.pop("book")
        response = self.client.post(
            self.url, data=data, content_type="application/json", **auth
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["book"], book.slug)
        response = self.client.post(
            self.url,
            data=[{**data, "what": "Bulk entry"}],
            content_type="application/json",
            **auth,
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["entries"][0]["book"], book.slug)
        self.factory.make_entry(book=other)
        response = self.client.get(self.url, **auth)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(
            {row["book"] for row in response.json()["results"]}, {book.slug}
        )
        response = self.client.post(
            f"{self.book_url(other.slug)}?book={book.slug}",
            data={**data, "what": "Explicit book"},
            content_type="application/json",
            **auth,
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["book"], other.slug)
        response = self.client.get(
            self.book_url(other.slug), {"book": book.slug}, **auth
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(
            {row["book"] for row in response.json()["results"]}, {other.slug}
        )

    def test_ambiguous_default_requires_an_explicit_book(self):
        auth = self.make_auth_header()
        book = self.factory.make_book(users=[self.api_user], default=True)
        self.factory.make_book(users=[self.api_user], default=True)
        data = self.make_entry_data(book_slug=book.slug)
        data.pop("book")
        for method in ("get", "post"):
            with self.subTest(method=method):
                response = getattr(self.client, method)(
                    self.url, data=data if method == "post" else {}, **auth
                )
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn("book", response.json())
        self.assertEqual(Entry.objects.count(), 0)
        response = self.client.get(self.book_url(book.slug), **auth)
        self.assertEqual(response.status_code, 200, response.content)

    def test_bulk_uses_tag_rules_and_reports_invalid_tags(self):
        auth = self.make_auth_header()
        data = self.make_entry_data()
        book = data.pop("book")
        data.pop("tags")
        account = Account.objects.get(slug=data["account"])
        tag, label = ChoicesMixin.TAG_CHOICES[0]
        self.factory.make_tag_regex(regex="^Matched", tag=tag, account=account)
        self.factory.make_tag_regex(
            regex="^Ambiguous", tag=TAGS[0], account=account
        )
        self.factory.make_tag_regex(
            regex="^Ambiguous", tag=TAGS[1], account=account
        )
        response = self.client.post(
            self.book_url(book),
            data=[
                {**data, "what": "Matched rule"},
                {**data, "what": "Tag by name", "tags": [label.upper()]},
                {**data, "what": "Invalid tag", "tags": [0]},
                {**data, "what": "Fallback tag"},
                {**data, "what": "Ambiguous rules"},
                {**data, "what": "Empty tags", "tags": []},
                {**data, "what": "Multiple tags", "tags": TAGS[:2]},
            ],
            content_type="application/json",
            **auth,
        )
        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()
        self.assertEqual(
            [row["tags"] for row in result["entries"]],
            [[tag], [tag], [settings.ENTRY_TAGS["default"]]],
        )
        self.assertEqual(result["errors"][0]["index"], 2)
        self.assertIn("tags", result["errors"][0]["errors"])
        self.assertEqual(
            [error["index"] for error in result["errors"]], [2, 4, 5, 6]
        )
        for error in result["errors"]:
            self.assertIn("tags", error["errors"])

    def test_default_resolution_uses_only_accessible_books(self):
        auth = self.make_auth_header()
        self.factory.make_book(default=True)
        for method in ("get", "post"):
            with self.subTest(method=method, books=0):
                response = getattr(self.client, method)(self.url, **auth)
                self.assertEqual(response.status_code, 404)
        book = self.factory.make_book(users=[self.api_user])
        data = self.make_entry_data(book_slug=book.slug)
        response = self.client.post(self.url, data=data, **auth)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["book"], book.slug)
        response = self.client.get(self.url, **auth)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["count"], 1)
        self.factory.make_book(users=[self.api_user])
        for method in ("get", "post"):
            with self.subTest(method=method, books=2):
                response = getattr(self.client, method)(
                    self.url, data=data if method == "post" else {}, **auth
                )
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn("book", response.json())
        self.assertEqual(Entry.objects.count(), 1)

    def test_legacy_ignores_book_in_query_and_each_entry(self):
        auth = self.make_auth_header()
        book = self.factory.make_book(users=[self.api_user], default=True)
        other = self.factory.make_book(users=[self.api_user])
        self.factory.make_entry(book=other)
        data = self.make_entry_data(book_slug=other.slug)
        url = f"{self.url}?book={other.slug}&book=missing-book"
        for supplied_book in (
            other.slug,
            "missing-book",
            None,
            {"slug": "bad"},
        ):
            with self.subTest(supplied_book=supplied_book):
                response = self.client.post(
                    url,
                    data={
                        **data,
                        "book": supplied_book,
                        "what": str(supplied_book),
                    },
                    content_type="application/json",
                    **auth,
                )
                self.assertEqual(response.status_code, 201, response.content)
                self.assertEqual(response.json()["book"], book.slug)
        response = self.client.post(
            url,
            data=[{**data, "what": "Bulk with ignored book"}],
            content_type="application/json",
            **auth,
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["entries"][0]["book"], book.slug)
        response = self.client.get(url, **auth)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["count"], 5)
        self.assertEqual(
            {row["book"] for row in response.json()["results"]}, {book.slug}
        )

    def test_post_rejects_unavailable_accounts_and_mismatched_books(self):
        auth = self.make_auth_header()
        book = self.factory.make_book(users=[self.api_user])
        other = self.factory.make_book(users=[self.api_user])
        unavailable = self.factory.make_account()
        inactive = self.factory.make_account(
            users=[self.api_user], active=False
        )
        data = self.make_entry_data(book_slug=book.slug)
        for changes, error_field in (
            ({"account": unavailable.slug}, "account"),
            ({"account": inactive.slug}, "account"),
            ({"book": other.slug}, "book"),
        ):
            with self.subTest(changes=changes):
                response = self.client.post(
                    self.book_url(book.slug),
                    data={**data, **changes},
                    content_type="application/json",
                    **auth,
                )
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn(error_field, response.json())
        self.assertEqual(Entry.objects.count(), 0)
        response = self.client.post(
            self.book_url(book.slug),
            data=[
                data,
                {**data, "book": other.slug, "what": "Wrong book"},
                {**data, "what": "Another valid entry"},
            ],
            content_type="application/json",
            **auth,
        )
        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()
        self.assertEqual(len(result["entries"]), 2)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["index"], 1)
        self.assertIn("book", result["errors"][0]["errors"])
        self.assertEqual(
            set(Entry.objects.values_list("book_id", flat=True)), {book.pk}
        )

    def test_bulk_keeps_valid_rows_and_reports_duplicates_and_invalid_rows(
        self,
    ):
        auth = self.make_auth_header()
        data = self.make_entry_data(when="2026-11-01", who="someone-else")
        book = data.pop("book")
        rows = [
            data,
            {**data, "amount": "-1"},
            data,
            "not an entry",
            {**data, "what": "Another entry", "is_income": True},
        ]
        response = self.client.post(
            self.book_url(book),
            data=rows,
            content_type="application/json",
            **auth,
        )
        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()
        self.assertEqual(len(result["entries"]), 2)
        self.assertEqual(
            [error["index"] for error in result["errors"]], [1, 2, 3]
        )
        self.assertIn("amount", result["errors"][0]["errors"])
        self.assertIn("non_field_errors", result["errors"][1]["errors"])
        entries = Entry.objects.order_by("id")
        self.assertEqual(entries.count(), 2)
        self.assertEqual(entries[0].when, date(2026, 11, 1))
        self.assertEqual(entries[0].who, self.api_user)
        self.assertIs(entries[0].is_income, False)
        self.assertIs(entries[1].is_income, True)
        self.assertEqual(
            [row["id"] for row in result["entries"]],
            list(entries.values_list("id", flat=True)),
        )
        retry = self.client.post(
            self.book_url(book),
            data=[rows[0], rows[-1]],
            content_type="application/json",
            **auth,
        )
        self.assertEqual(retry.status_code, 400, retry.content)
        self.assertEqual(retry.json()["entries"], [])
        self.assertEqual(len(retry.json()["errors"]), 2)
        self.assertEqual(Entry.objects.count(), 2)

    def test_empty_bulk_is_rejected(self):
        auth = self.make_auth_header()
        book = self.factory.make_book(users=[self.api_user])
        response = self.client.post(
            self.book_url(book.slug),
            data=[],
            content_type="application/json",
            **auth,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Entry.objects.count(), 0)

    def test_get_filters_are_combined_and_scoped_to_book(self):
        auth = self.make_auth_header()
        book = self.factory.make_book(users=[self.api_user])
        url = self.book_url(book.slug)
        account = self.factory.make_account(users=[self.api_user])
        other_account = self.factory.make_account(currency="EUR")
        other_user = self.factory.make_user()
        first_tag, second_tag = TAGS[:2]
        common = dict(
            book=book,
            account=account,
            who=self.api_user,
            when=date(2026, 11, 1),
            country="US",
            tags=[first_tag],
            is_income=False,
        )
        first = self.factory.make_entry(**common)
        last = self.factory.make_entry(
            **{**common, "when": date(2026, 11, 30)}
        )
        different = {}
        for field, value in (
            ("book", self.factory.make_book()),
            ("account", other_account),
            ("who", other_user),
            ("country", "AR"),
            ("tags", [second_tag]),
            ("is_income", True),
            ("when", date(2026, 12, 1)),
        ):
            different[field] = self.factory.make_entry(
                **{**common, field: value}
            )
        params = {
            "account": account.slug,
            "start": "2026-11-01",
            "end": "2026-11-30",
            "country": "US",
            "currency": "USD",
            "who": self.api_user.username,
            "tag": [first_tag],
            "is_income": "false",
        }
        response = self.client.get(url, params, **auth)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            [row["id"] for row in response.json()["results"]],
            [last.pk, first.pk],
        )
        response = self.client.get(
            url, {**params, "tag": [first_tag, second_tag]}, **auth
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])
        for field, value, expected in (
            ("account", other_account.slug, different["account"]),
            ("currency", "EUR", different["account"]),
            ("who", other_user.username, different["who"]),
            ("country", "AR", different["country"]),
            ("is_income", "true", different["is_income"]),
            ("start", "2026-12-01", different["when"]),
        ):
            with self.subTest(field=field):
                response = self.client.get(url, {field: value}, **auth)
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(
                    [row["id"] for row in response.json()["results"]],
                    [expected.pk],
                )
        response = self.client.get(url, **auth)
        self.assertEqual(response.json()["count"], 8)
        self.assertIn(
            different["is_income"].pk,
            [row["id"] for row in response.json()["results"]],
        )

    def test_get_rejects_invalid_or_ambiguous_filters(self):
        auth = self.make_auth_header()
        book = self.factory.make_book(users=[self.api_user])
        for params, error_field in (
            ({"start": "2026-11-31"}, "start"),
            ({"start": "not-a-date"}, "start"),
            ({"start": "2026-11-02", "end": "2026-11-01"}, "end"),
            ({"currency": "invalid"}, "currency"),
            ({"country": "invalid"}, "country"),
            ({"is_income": "invalid"}, "is_income"),
            ({"tag": ["invalid"]}, "tag"),
            ({"page": "invalid"}, "page"),
            ({"page": 0}, "page"),
            ({"page_size": 0}, "page_size"),
            ({"page_size": 101}, "page_size"),
            ({"country": ["US", "AR"]}, "country"),
            ({"q": "unsupported"}, "q"),
        ):
            with self.subTest(params=params):
                response = self.client.get(
                    self.book_url(book.slug), params, **auth
                )
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn(error_field, response.json())

    def test_get_pagination_is_stable_and_preserves_filters(self):
        auth = self.make_auth_header()
        book = self.factory.make_book(users=[self.api_user])
        url = self.book_url(book.slug)
        account = self.factory.make_account(
            users=[self.api_user], active=False
        )
        entries = [
            self.factory.make_entry(
                book=book,
                account=account,
                when=date(2026, 11, 1),
                what="Same description",
                amount=Decimal(index + 1),
                country="US",
            )
            for index in range(26)
        ]
        response = self.client.get(url, **auth)
        self.assertEqual(response.status_code, 200, response.content)
        result = response.json()
        self.assertEqual(result["count"], 26)
        self.assertEqual(len(result["results"]), 25)
        self.assertIsNone(result["previous"])
        self.assertEqual(result["results"][0]["id"], entries[0].pk)
        params = {"country": "US", "page_size": "2", "format": "json"}
        response = self.client.get(url, params, **auth)
        result = response.json()
        self.assertEqual(
            [row["id"] for row in result["results"]],
            [entry.pk for entry in entries[:2]],
        )
        next_url = urlsplit(result["next"])
        self.assertEqual(
            parse_qs(next_url.query),
            {**{key: [value] for key, value in params.items()}, "page": ["2"]},
        )
        response = self.client.get(f"{next_url.path}?{next_url.query}", **auth)
        self.assertEqual(
            [row["id"] for row in response.json()["results"]],
            [entry.pk for entry in entries[2:4]],
        )
        for page, page_size in (("2", "2"), ("2.0", "2.0"), ("2.00", "2.00")):
            with self.subTest(page=page, page_size=page_size):
                response = self.client.get(
                    url,
                    {**params, "page": page, "page_size": page_size},
                    **auth,
                )
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(
                    [row["id"] for row in response.json()["results"]],
                    [entry.pk for entry in entries[2:4]],
                )
        response = self.client.get(url, {"page": 100}, **auth)
        self.assertEqual(response.status_code, 404)

    def test_get_respects_configured_format_parameter(self):
        auth = self.make_auth_header()
        book = self.factory.make_book(users=[self.api_user])
        for name in ("format", "representation", None):
            with (
                self.subTest(name=name),
                override_settings(
                    REST_FRAMEWORK={"URL_FORMAT_OVERRIDE": name}
                ),
            ):
                response = self.client.get(
                    self.book_url(book.slug),
                    {name or "format": "json"},
                    **auth,
                )
                if name is None:
                    self.assertEqual(
                        response.status_code, 400, response.content
                    )
                    self.assertIn("format", response.json())
                else:
                    self.assertEqual(
                        response.status_code, 200, response.content
                    )
                    self.assertEqual(response.json()["results"], [])

    def test_add_expense_script_respects_selected_book(self):
        auth = self.make_auth_header()
        default = self.factory.make_book(users=[self.api_user], default=True)
        other = self.factory.make_book(users=[self.api_user])
        account = self.factory.make_account(users=[self.api_user])
        script = settings.BASE_DIR / "scripts" / "add-expense.py"

        def post(url, json, headers):
            self.assertEqual(url, f"http://testserver{expected_url}")
            response = self.client.post(
                urlsplit(url).path,
                data=json,
                content_type="application/json",
                HTTP_AUTHORIZATION=headers["Authorization"],
            )
            self.assertEqual(response.status_code, 201, response.content)
            self.assertEqual(response.json()["book"], expected_book.slug)
            return SimpleNamespace(
                ok=True, status_code=response.status_code, json=response.json
            )

        for book_slug, expected_book in ((None, default), (other.slug, other)):
            expected_url = self.book_url(book_slug) if book_slug else self.url
            argv = [str(script), "--account", account.slug, "Lunch", "12.50"]
            if book_slug:
                argv.extend(["--book", book_slug])
            with (
                self.subTest(book_slug=book_slug),
                patch.dict(
                    os.environ,
                    CGEM_TOKEN=auth["HTTP_AUTHORIZATION"].split()[1],
                    CGEM_ROOT_URL="http://testserver",
                ),
                patch.dict("sys.modules", requests=SimpleNamespace(post=post)),
                patch("sys.argv", argv),
                redirect_stdout(StringIO()),
            ):
                runpy.run_path(str(script), run_name="__main__")
        self.assertEqual(Entry.objects.filter(book=default).count(), 1)
        self.assertEqual(Entry.objects.filter(book=other).count(), 1)
