from datetime import UTC, date, datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.http import HttpResponse, HttpResponseRedirect
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse
from django.utils.html import escape
from django.utils.timezone import override
from django_htmx.middleware import HtmxMiddleware

from gemcore.constants import TAGS
from gemcore.forms import (
    AccountTransferForm,
    BalanceForm,
    EntryForm,
    EntryMergeForm,
)
from gemcore.middleware import HtmxRedirectMiddleware
from gemcore.tests.helpers import BaseTestCase, ElementCollector

DEFAULT_PASSWORD = "test"


class HtmxRedirectMiddlewareTestCase(SimpleTestCase):
    factory = RequestFactory()

    def response_for(self, response, *, htmx):
        headers = {"HX-Request": "true"} if htmx else {}
        request = self.factory.get("/", headers=headers)
        middleware = HtmxMiddleware(
            HtmxRedirectMiddleware(lambda request: response)
        )
        return middleware(request)

    def test_htmx_302_becomes_client_redirect(self):
        response = self.response_for(
            HttpResponseRedirect("/login/?next=/book/"), htmx=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Redirect"], "/login/?next=/book/")
        self.assertNotIn("Location", response.headers)
        self.assertEqual(response.content, b"")

    def test_plain_302_passes_through(self):
        redirect = HttpResponseRedirect("/login/?next=/book/")
        response = self.response_for(redirect, htmx=False)
        self.assertIs(response, redirect)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("HX-Redirect", response.headers)

    def test_htmx_non_redirect_passes_through(self):
        original = HttpResponse("Form errors")
        response = self.response_for(original, htmx=True)
        self.assertIs(response, original)
        self.assertEqual(response.content, b"Form errors")
        self.assertNotIn("HX-Redirect", response.headers)

    def test_other_redirect_statuses_pass_through(self):
        for status in (301, 303, 307, 308):
            with self.subTest(status=status):
                original = HttpResponseRedirect("/book/", status=status)
                response = self.response_for(original, htmx=True)
                self.assertIs(response, original)
                self.assertNotIn("HX-Redirect", response.headers)


class LoginViewTestCase(BaseTestCase):
    def test_invalid_fields_keep_accessible_error_associations(self):
        response = self.client.post(
            reverse("login"), {"username": "", "password": ""}
        )
        elements = ElementCollector(response.content.decode()).elements
        ids = {attrs["id"] for tag, attrs in elements if "id" in attrs}
        inputs = {
            attrs["name"]: attrs
            for tag, attrs in elements
            if tag == "input" and "name" in attrs
        }
        for name in ("username", "password"):
            with self.subTest(name=name):
                self.assertEqual(inputs[name]["aria-invalid"], "true")
                for error_id in inputs[name]["aria-describedby"].split():
                    self.assertIn(error_id, ids)

    def test_login_preserves_destination_and_accepts_credentials(self):
        user = self.factory.make_user(password=DEFAULT_PASSWORD)
        book = self.factory.make_book(users=[user])
        destination = reverse("entries", args=[book.slug]) + "?q=coffee"
        response = self.client.get(reverse("login"), {"next": destination})
        elements = ElementCollector(response.content.decode()).elements
        inputs = {
            attrs["name"]: attrs
            for tag, attrs in elements
            if tag == "input" and "name" in attrs
        }
        self.assertEqual(inputs["next"]["value"], destination)
        self.assertEqual(inputs["password"]["type"], "password")
        self.assertIn("csrfmiddlewaretoken", inputs)

        response = self.client.post(
            reverse("login"),
            {
                "username": user.username,
                "password": DEFAULT_PASSWORD,
                "next": inputs["next"]["value"],
            },
        )
        self.assertRedirects(response, destination)

    def test_logout_uses_post(self):
        user = self.factory.make_user()
        self.client.force_login(user)
        response = self.client.get(reverse("books"))
        elements = ElementCollector(response.content.decode()).elements
        forms = [
            attrs
            for tag, attrs in elements
            if tag == "form" and attrs.get("action") == reverse("logout")
        ]
        self.assertEqual(len(forms), 1)
        self.assertEqual(forms[0]["method"], "post")
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, "/", fetch_redirect_response=False)


class AddEntryTestCase(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = cls.factory.make_user(password=DEFAULT_PASSWORD)
        cls.book = cls.factory.make_book(users=[cls.user])
        cls.account = cls.factory.make_account(users=[cls.user])

    def test_htmx_requests_without_session_redirect_to_login(self):
        url = reverse("entries", args=[self.book.slug])
        for method in ("get", "post"):
            with self.subTest(method=method):
                plain = getattr(self.client, method)(url)
                self.assertEqual(plain.status_code, 302)
                response = getattr(self.client, method)(
                    url, headers={"HX-Request": "true"}
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["HX-Redirect"], plain["Location"])
                self.assertNotIn("Location", response.headers)

    def test_htmx_login_keeps_authenticated_session(self):
        destination = reverse("entries", args=[self.book.slug])
        response = self.client.post(
            reverse("login"),
            {
                "username": self.user.username,
                "password": DEFAULT_PASSWORD,
                "next": destination,
            },
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Redirect"], destination)
        self.assertEqual(self.client.session[SESSION_KEY], str(self.user.pk))

    @override_settings(DATE_FORMAT="d/m/Y", LANGUAGE_CODE="fr")
    def test_date_widgets_use_iso_format(self):
        fields = (
            BalanceForm.base_fields["start"],
            BalanceForm.base_fields["end"],
            EntryForm.base_fields["when"],
            EntryMergeForm.base_fields["when"],
            AccountTransferForm.base_fields["when"],
        )
        for field in fields:
            with self.subTest(field=field):
                self.assertEqual(
                    field.widget.format_value(date(2026, 11, 3)),
                    "2026-11-03",
                )

    def test_integrity_error_handled(self):
        assert self.client.login(
            username=self.user.username, password=DEFAULT_PASSWORD
        )
        tag = TAGS[0]
        existing = self.factory.make_entry(
            book=self.book,
            account=self.account,
            who=self.user,
            amount=10,
            what="test",
            tags=[tag],
            country="US",
        )
        url = reverse("add-entry", kwargs={"book_slug": self.book.slug})

        data = dict(
            who=self.user.id,
            amount=10,
            what="test",
            country="US",
            when=existing.when.isoformat(),
            account=self.account.id,
            tags=[tag],
        )
        response = self.client.post(url, data=data, follow=True)

        error = "There is already an entry for this data."
        form = response.context["form"]
        self.assertFormError(form, field=None, errors=[error])
        self.assertContains(response, 'role="alert"')

    def test_edit_preserves_radio_selection_and_return_filters(self):
        entry = self.factory.make_entry(
            book=self.book,
            account=self.account,
            who=self.user,
            tags=[TAGS[0]],
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("entry", args=[self.book.slug, entry.pk]),
            {"q": "coffee", "tag": TAGS[0]},
        )
        elements = ElementCollector(response.content.decode()).elements
        selected = [
            attrs
            for tag, attrs in elements
            if tag == "input"
            and attrs.get("name") == "tags"
            and "checked" in attrs
        ]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["type"], "radio")
        self.assertEqual(selected[0]["value"], TAGS[0])
        hidden_filters = next(
            attrs["value"]
            for tag, attrs in elements
            if tag == "input" and attrs.get("name") == "qs"
        )
        self.assertEqual(
            parse_qs(hidden_filters), {"q": ["coffee"], "tag": [TAGS[0]]}
        )
        expected = (
            reverse("entries", args=[self.book.slug]) + "?" + hidden_filters
        )
        self.assertIn(
            expected,
            [attrs.get("href") for tag, attrs in elements if tag == "a"],
        )


class AccountTransferTestCase(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = cls.factory.make_user(password=DEFAULT_PASSWORD)
        cls.book = cls.factory.make_book(users=[cls.user])
        cls.source_account = cls.factory.make_account(users=[cls.user])
        cls.target_account = cls.factory.make_account(users=[cls.user])

    def test_date_default_follows_utc_midnight(self):
        instants = (
            datetime(2026, 12, 31, 23, 59, tzinfo=UTC),
            datetime(2027, 1, 1, 0, 1, tzinfo=UTC),
        )
        for offset in (-12, 14):
            for instant in instants:
                with (
                    self.subTest(offset=offset, instant=instant),
                    override(timezone(timedelta(hours=offset))),
                    patch("gemcore.models.now", return_value=instant),
                ):
                    form = AccountTransferForm(book=self.book)
                    self.assertEqual(form["when"].value(), instant.date())

    def test_transfer_entries_use_correct_tag(self):
        url = reverse("account-transfer", args=[self.book.slug])

        data = {
            "source_account": self.source_account.id,
            "source_amount": "10.00",
            "target_account": self.target_account.id,
            "target_amount": "11.00",
            "what": "Transfer test",
            "when": "2026-05-03",
            "country": "US",
        }

        assert self.client.login(
            username=self.user.username, password=DEFAULT_PASSWORD
        )
        response = self.client.post(url, data=data)

        self.assertRedirects(
            response, reverse("entries", args=[self.book.slug])
        )
        entries = list(self.book.entry_set.order_by("id"))
        self.assertEqual(len(entries), 2)
        self.assertEqual(
            entries[0].tags, [settings.ENTRY_ACCOUNT_TRANSFER_TAG]
        )
        self.assertEqual(entries[0].amount, 10.00)
        self.assertEqual(entries[0].what, "Transfer test (source)")

        self.assertEqual(
            entries[1].tags, [settings.ENTRY_ACCOUNT_TRANSFER_TAG]
        )
        self.assertEqual(entries[1].amount, 11.00)
        self.assertEqual(entries[1].what, "Transfer test (target)")

    def test_invalid_transfer_displays_errors_without_creating_entries(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("account-transfer", args=[self.book.slug]),
            {
                "source_account": self.source_account.pk,
                "target_account": self.source_account.pk,
                "source_amount": "10.00",
                "target_amount": "10.00",
                "what": "Transfer test",
                "when": "2026-11-06",
                "country": "US",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["book"], self.book)
        self.assertFormError(
            response.context["form"],
            None,
            ["Source account can not be the same as the target account."],
        )
        self.assertContains(response, 'role="alert"')
        self.assertEqual(self.book.entry_set.count(), 0)


class BalanceViewTestCase(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = cls.factory.make_user(password=DEFAULT_PASSWORD)
        cls.book = cls.factory.make_book(users=[cls.user])
        cls.account = cls.factory.make_account(users=[cls.user])

    def test_get_by_account(self):
        kwargs = {
            "book_slug": self.book.slug,
            "account_slug": self.account.slug,
        }
        url = reverse("balance", kwargs=kwargs)

        assert self.client.login(
            username=self.user.username, password=DEFAULT_PASSWORD
        )
        response = self.client.get(url)

        self.assertContains(response, "Balances for %s" % self.book.name)

    def test_get_by_currency(self):
        kwargs = {
            "book_slug": self.book.slug,
            "currency": self.account.currency,
        }
        url = reverse("balance", kwargs=kwargs)

        assert self.client.login(
            username=self.user.username, password=DEFAULT_PASSWORD
        )
        response = self.client.get(url)

        self.assertContains(response, "Balances for %s" % self.book.name)

    def test_balance_forms_have_distinct_ids_and_keep_invalid_values(self):
        self.client.force_login(self.user)
        url = reverse("balance", args=[self.book.slug])
        response = self.client.get(url)
        elements = ElementCollector(response.content.decode()).elements
        ids = [attrs["id"] for tag, attrs in elements if "id" in attrs]
        self.assertEqual(len(ids), len(set(ids)))

        for action, source, context_name in (
            ("get-account-balance", self.account.pk, "account_balance_form"),
            (
                "get-currency-balance",
                self.account.currency,
                "currency_balance_form",
            ),
        ):
            with self.subTest(action=action):
                response = self.client.post(
                    url, {action: "", "source": source, "start": "invalid"}
                )
                form = response.context[context_name]
                self.assertFormError(form, "start", ["Enter a valid date."])
                self.assertEqual(form["start"].value(), "invalid")
                self.assertContains(response, "Enter a valid date.")


class BookPagesTestCase(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = cls.factory.make_user()
        cls.book = cls.factory.make_book(users=[cls.user])
        cls.account = cls.factory.make_account(users=[cls.user])

    def test_book_pages_and_forms_render(self):
        self.client.force_login(self.user)
        for name, args in (
            ("books", []),
            ("add-book", []),
            ("book", [self.book.slug]),
            ("entries", [self.book.slug]),
            ("add-entry", [self.book.slug]),
            ("balance", [self.book.slug]),
            ("load-from-file", [self.book.slug]),
            ("account-transfer", [self.book.slug]),
        ):
            with self.subTest(name=name):
                response = self.client.get(reverse(name, args=args))
                self.assertEqual(response.status_code, 200)

    def test_pagination_preserves_filters_and_bulk_selection(self):
        for index in range(3):
            self.factory.make_entry(
                book=self.book,
                account=self.account,
                who=self.user,
                what=f"Coffee {index}",
                tags=[TAGS[0]],
                country="US",
            )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("entries", args=[self.book.slug]),
            {"q": "Coffee", "tag": TAGS[0], "country": "US", "page_size": 1},
        )
        self.assertContains(response, 'aria-label="Entries pages"', count=2)
        elements = ElementCollector(response.content.decode()).elements
        page_links = [
            parse_qs(urlsplit(attrs["href"]).query)
            for tag, attrs in elements
            if tag == "a"
            and "href" in attrs
            and parse_qs(urlsplit(attrs["href"]).query).get("page") == ["2"]
        ]
        self.assertGreater(len(page_links), 0)
        for query in page_links:
            self.assertEqual(query["q"], ["Coffee"])
            self.assertEqual(query["tag"], [TAGS[0]])
            self.assertEqual(query["country"], ["US"])
        selections = [
            attrs
            for tag, attrs in elements
            if tag == "input" and attrs.get("name") == "entry"
        ]
        self.assertEqual(len(selections), 1)
        self.assertEqual(selections[0]["type"], "checkbox")
        self.assertEqual(
            selections[0]["value"], str(response.context["entries"][0].pk)
        )
        for form_name in (
            "edit_account_form",
            "edit_asset_form",
            "edit_tags_form",
            "edit_country_form",
        ):
            self.assertIs(response.context[form_name].is_bound, False)

    def test_inline_balance_preserves_htmx_target_and_supports_currencies(
        self,
    ):
        entry = self.factory.make_entry(
            book=self.book,
            account=self.account,
            who=self.user,
            amount=10,
            is_income=False,
        )
        other_account = self.factory.make_account(
            users=[self.user], currency="EUR"
        )
        other = self.factory.make_entry(
            book=self.book,
            account=other_account,
            who=self.user,
            amount=20,
            is_income=True,
        )
        self.client.force_login(self.user)
        url = reverse("entries", args=[self.book.slug])
        response = self.client.get(url)
        elements = ElementCollector(response.content.decode()).elements
        buttons = [
            attrs
            for tag, attrs in elements
            if tag == "button" and attrs.get("name") == "calculate-balance"
        ]
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0]["hx-post"], ".")
        self.assertEqual(buttons[0]["hx-target"], "#entries-balance-inline")
        self.assertEqual(buttons[0]["hx-trigger"], "click")

        for selected in ([entry.pk], [entry.pk, other.pk]):
            with self.subTest(selected=selected):
                response = self.client.post(
                    url,
                    {"entry": selected, "calculate-balance": ""},
                    headers={"HX-Request": "true"},
                )
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, "<html")
                self.assertContains(
                    response, "Monthly balance", count=len(selected)
                )
        self.assertEqual(self.book.entry_set.count(), 2)


class BulkTestCaseMixin:
    action_name = ""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = cls.factory.make_user(password=DEFAULT_PASSWORD)
        cls.book = cls.factory.make_book(users=[cls.user])

    def do_request(self, method="GET", **kwargs):
        url = reverse("entries", args=[self.book.slug])

        assert self.client.login(
            username=self.user.username, password=DEFAULT_PASSWORD
        )
        return getattr(self.client, method.lower())(url, follow=True, **kwargs)

    def test_no_action_shown_if_no_entries(self):
        response = self.do_request()

        assert self.action_name
        self.assertNotContains(response, f'name="{self.action_name}"')

    def test_button_shown_if_entries_available(self):
        for i in range(3):
            self.factory.make_entry(book=self.book, who=self.user)

        response = self.do_request()

        self.assertContains(response, f'name="{self.action_name}"')


class BulkRemoveTestCase(BulkTestCaseMixin, BaseTestCase):
    action_name = "remove-selected"

    def test_book_in_context_on_remove_post(self):
        entries = [
            self.factory.make_entry(book=self.book, who=self.user)
            for i in range(3)
        ]

        assert self.action_name
        data = {"entry": [e.id for e in entries], self.action_name: 1}
        response = self.do_request(method="POST", data=data)

        msg = "Are you sure you want to remove these entries?"
        self.assertContains(response, msg)

        for e in entries:
            self.assertContains(response, escape(str(e)))
            self.assertInHTML(
                f'<input type="hidden" name="entry" value="{e.id}">',
                response.content.decode(),
            )

        self.assertEqual(self.book, response.context.get("book"))

        url = reverse("remove-entry", args=[self.book.slug])
        self.assertContains(
            response, '<form action="%s?" method="POST">' % url
        )

    def test_single_entry_confirmation_keeps_book_and_filters(self):
        entry = self.factory.make_entry(book=self.book, who=self.user)
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("remove-entry", args=[self.book.slug, entry.pk]),
            {"country": entry.country},
        )
        self.assertEqual(response.context["book"], self.book)
        self.assertEqual(
            parse_qs(response.context["qs"]), {"country": [entry.country]}
        )
        self.assertInHTML(
            f'<input type="hidden" name="entry" value="{entry.pk}">',
            response.content.decode(),
        )
        self.assertEqual(self.book.entry_set.count(), 1)


class BulkMergeTestCase(BulkTestCaseMixin, BaseTestCase):
    action_name = "merge-selected"


class BulkChangeAccountTestCase(BulkTestCaseMixin, BaseTestCase):
    action_name = "change-account"


class BulkChangeTagTestCase(BulkTestCaseMixin, BaseTestCase):
    action_name = "change-tags"

    def test_tags_changed(self):
        # make many entries
        unchanged = [
            self.factory.make_entry(book=self.book, who=self.user, tags=[t])
            for t in TAGS
        ]
        entries = [
            self.factory.make_entry(book=self.book, who=self.user, tags=[t])
            for t in TAGS
        ]

        assert self.action_name
        target_tag = TAGS[0]
        data = {
            "entry": [e.id for e in entries],
            self.action_name: 1,
            "tags-target": target_tag,
        }
        response = self.do_request(method="POST", data=data)

        self.assertRedirects(
            response, reverse("entries", args=[self.book.slug])
        )
        msg = ", ".join(str(e) for e in entries)
        self.assert_messages(
            response,
            error=[],
            success=[f'Entries "{msg}" changed with tags "{target_tag}".'],
        )
        for e in entries:
            e.refresh_from_db()
            self.assertEqual(e.tags, [target_tag])
        for i, e in enumerate(unchanged):
            e.refresh_from_db()
            self.assertEqual(e.tags, unchanged[i].tags)
