from datetime import UTC, date, datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

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

    def test_account_change_requests_country_fragment(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("add-entry", args=[self.book.slug]))
        elements = ElementCollector(response.content.decode()).elements
        account = next(
            attrs
            for tag, attrs in elements
            if tag == "div" and attrs.get("id") == "entry-account"
        )
        self.assertEqual(
            account["hx-get"], reverse("entry-country", args=[self.book.slug])
        )
        self.assertEqual(account["hx-trigger"], "change")
        self.assertEqual(account["hx-target"], "#entry-country")
        self.assertEqual(account["hx-swap"], "outerHTML")
        self.assertEqual(account["hx-include"], "#id_account,#id_country")
        self.assertEqual(account["hx-sync"], "this:replace")
        self.assertEqual(
            account["hx-disabled-elt"],
            "#entry-save-actions button[type=submit]:not([disabled]), "
            "#id_country:not([disabled])",
        )
        self.assertContains(response, 'id="entry-save-actions"', count=1)
        account_select = next(
            attrs
            for tag, attrs in elements
            if tag == "select" and attrs.get("name") == "account"
        )
        self.assertIs(
            any(name.startswith("hx-") for name in account_select), False
        )
        self.assertNotContains(response, "js/add-entry.js")

    def test_country_suggestion_uses_currency_and_preserves_unmapped_values(
        self,
    ):
        self.client.force_login(self.user)
        url = reverse("entry-country", args=[self.book.slug])
        for currency, expected in (
            ("ARS", "AR"),
            ("BRL", "BR"),
            ("CAD", "CA"),
            ("CNY", "CN"),
            ("EUR", ""),
            ("GBP", "GB"),
            ("USD", "US"),
            ("UYU", "UY"),
            ("CHF", "BR"),
        ):
            with self.subTest(currency=currency):
                account = self.factory.make_account(
                    users=[self.user],
                    currency=currency,
                    name="ARS misleading label",
                )
                response = self.client.get(
                    url,
                    {"account": account.pk, "country": "BR"},
                    headers={"HX-Request": "true"},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.context["form"]["country"].value(), expected
                )
                self.assertNotContains(response, "<html")
                self.assertContains(response, 'id="entry-country"', count=1)
                options = ElementCollector(response.content.decode()).elements
                self.assertEqual(
                    [
                        attrs["value"]
                        for tag, attrs in options
                        if tag == "option" and "selected" in attrs
                    ],
                    [expected],
                )

        response = self.client.get(url, {"account": "", "country": "CA"})
        self.assertEqual(response.context["form"]["country"].value(), "CA")
        self.assertEqual(self.book.entry_set.count(), 0)

    def test_country_suggestion_checks_access_and_requires_get(self):
        url = reverse("entry-country", args=[self.book.slug])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.user)
        other_account = self.factory.make_account()
        inactive_account = self.factory.make_account(
            users=[self.user], active=False
        )
        for account in (other_account.pk, inactive_account.pk, "invalid", -1):
            with self.subTest(account=account):
                response = self.client.get(url, {"account": account})
                self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.post(url).status_code, 405)
        other_book = self.factory.make_book()
        response = self.client.get(
            reverse("entry-country", args=[other_book.slug]),
            {"account": self.account.pk},
        )
        self.assertEqual(response.status_code, 404)

    def test_country_defaults_do_not_override_saved_or_submitted_country(self):
        entry = self.factory.make_entry(
            book=self.book, account=self.account, who=self.user, country="BR"
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("add-entry", args=[self.book.slug]))
        self.assertEqual(response.context["form"]["country"].value(), "US")
        response = self.client.get(
            reverse("entry", args=[self.book.slug, entry.pk])
        )
        self.assertEqual(response.context["form"]["country"].value(), "BR")
        response = self.client.post(
            reverse("add-entry", args=[self.book.slug]),
            {"account": self.account.pk, "country": "CA"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"]["country"].value(), "CA")
        self.assertEqual(self.book.entry_set.count(), 1)

    def test_adjacent_entries_follow_filtered_list_order(self):
        ordered = []
        for when, what, amount in (
            (date(2026, 11, 7), "Coffee newest", 1),
            (date(2026, 11, 6), "Coffee A", 1),
            (date(2026, 11, 6), "Coffee B", 1),
            (date(2026, 11, 6), "Coffee B", 2),
            (date(2026, 11, 5), "Coffee oldest", 1),
        ):
            ordered.append(
                self.factory.make_entry(
                    book=self.book,
                    account=self.account,
                    who=self.user,
                    when=when,
                    what=what,
                    amount=amount,
                    country="US",
                    tags=[TAGS[0]],
                )
            )
        self.factory.make_entry(
            book=self.book, who=self.user, what="Tea", country="US"
        )
        self.factory.make_entry(
            book=self.book, who=self.user, what="Coffee excluded", country="AR"
        )
        self.factory.make_entry(what="Coffee private", country="US")
        params = {
            "q": "Coffee",
            "country": "US",
            "page": "2",
            "page_size": "2",
            "include_tag": TAGS[:2],
        }
        self.client.force_login(self.user)
        for index, entry in enumerate(ordered):
            with self.subTest(index=index):
                response = self.client.get(
                    reverse("entry", args=[self.book.slug, entry.pk]), params
                )
                previous = ordered[index - 1] if index else None
                following = (
                    ordered[index + 1] if index + 1 < len(ordered) else None
                )
                self.assertEqual(response.context["entry_prev"], previous)
                self.assertEqual(response.context["entry_next"], following)
                expected_query = parse_qs(urlencode(params, doseq=True))
                self.assertEqual(
                    parse_qs(response.context["qs"]), expected_query
                )
                elements = ElementCollector(response.content.decode()).elements
                links = [
                    attrs["href"]
                    for tag, attrs in elements
                    if tag == "a" and "href" in attrs
                ]
                for adjacent in (previous, following):
                    if adjacent:
                        path = reverse(
                            "entry", args=[self.book.slug, adjacent.pk]
                        )
                        link = next(
                            link
                            for link in links
                            if urlsplit(link).path == path
                        )
                        self.assertEqual(
                            parse_qs(urlsplit(link).query), expected_query
                        )
                remove_path = reverse(
                    "remove-entry", args=[self.book.slug, entry.pk]
                )
                remove_link = next(
                    link
                    for link in links
                    if urlsplit(link).path == remove_path
                )
                self.assertEqual(
                    parse_qs(urlsplit(remove_link).query), expected_query
                )
                for changed in (
                    {"when": "2026-12-01", "what": ""},
                    {"when": "2026-11-06", "what": "Coffee Z"},
                ):
                    response = self.client.post(
                        reverse("entry", args=[self.book.slug, entry.pk])
                        + "?"
                        + urlencode(params, doseq=True),
                        {
                            "who": self.user.pk,
                            "account": self.account.pk,
                            "country": "US",
                            "tags": TAGS[0],
                            "qs": urlencode(params, doseq=True),
                            **changed,
                        },
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertIs(response.context["form"].is_valid(), False)
                    self.assertEqual(response.context["entry_prev"], previous)
                    self.assertEqual(response.context["entry_next"], following)
                    for field, value in changed.items():
                        self.assertEqual(
                            response.context["form"][field].value(), value
                        )
                saved = self.book.entry_set.get(pk=entry.pk)
                self.assertEqual(saved.when, entry.when)
                self.assertEqual(saved.what, entry.what)

    def test_save_destinations_preserve_return_filters_and_page(self):
        self.client.force_login(self.user)
        params = {
            "q": "Coffee",
            "when": "2026-10-31",
            "page": "2",
            "page_size": "1",
            "include_tag": TAGS[:2],
        }
        qs = urlencode(params, doseq=True)
        add_url = reverse("add-entry", args=[self.book.slug])
        for index, action in enumerate(
            (
                "save-and-new",
                "save-and-new-same-date",
                "save-and-edit",
                "save-and-go-back",
            )
        ):
            with self.subTest(action=action):
                data = {
                    "who": self.user.pk,
                    "account": self.account.pk,
                    "what": f"Coffee saved {index}",
                    "amount": "10.00",
                    "when": "2026-11-01",
                    "country": "US",
                    "tags": TAGS[0],
                    "qs": qs,
                    action: "",
                }
                response = self.client.post(add_url + "?" + qs, data)
                self.assertEqual(response.status_code, 302)
                destination = response["Location"]
                query = parse_qs(urlsplit(destination).query)
                expected = parse_qs(qs)
                if action == "save-and-new-same-date":
                    expected["initial_when"] = ["2026-11-01"]
                self.assertEqual(query, expected)
                if action in {"save-and-new", "save-and-new-same-date"}:
                    self.assertEqual(urlsplit(destination).path, add_url)
                elif action == "save-and-go-back":
                    self.assertEqual(
                        urlsplit(destination).path,
                        reverse("entries", args=[self.book.slug]),
                    )
                else:
                    saved = self.book.entry_set.get(what=data["what"])
                    self.assertEqual(
                        urlsplit(destination).path,
                        reverse("entry", args=[self.book.slug, saved.pk]),
                    )
                if action != "save-and-go-back":
                    next_page = self.client.get(destination)
                    self.assertEqual(
                        parse_qs(next_page.context["qs"]), parse_qs(qs)
                    )
                    if action == "save-and-new-same-date":
                        self.assertEqual(
                            next_page.context["form"]["when"].value(),
                            "2026-11-01",
                        )
        invalid = self.client.post(add_url + "?" + qs, {"qs": qs})
        self.assertEqual(invalid.status_code, 200)
        self.assertEqual(parse_qs(invalid.context["qs"]), parse_qs(qs))


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
        self.assertEqual(buttons[0]["hx-post"], url)
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
                self.assertContains(response, "selected entr")
        response = self.client.post(
            url,
            {"update-selection": "change", "entry": [other.pk]},
            headers={"HX-Request": "true"},
        )
        self.assertNotContains(response, "Monthly balance")
        self.assertNotContains(response, 'id="selection-balance-heading"')
        self.assertEqual(self.book.entry_set.count(), 2)

    def test_selection_updates_count_and_available_actions_without_writing(
        self,
    ):
        entries = [
            self.factory.make_entry(
                book=self.book, account=self.account, who=self.user
            )
            for _ in range(2)
        ]
        self.client.force_login(self.user)
        url = reverse("entries", args=[self.book.slug])
        response = self.client.get(url)
        for name in ("edit_tags_form", "edit_country_form"):
            choices = list(response.context[name].fields["target"].choices)
            self.assertEqual(choices[0][0], "")
        self.assertIs(response.context["no_selection"], True)
        self.assertIs(response.context["cannot_merge"], True)
        for selection_action, selected, select_page, expected_count in (
            ("change", [entries[0].pk], "", 1),
            ("page", [], "all", 2),
            ("page", [entry.pk for entry in entries], "", 0),
            ("clear", [entry.pk for entry in entries], "all", 0),
        ):
            with self.subTest(action=selection_action):
                response = self.client.post(
                    url,
                    {
                        "update-selection": selection_action,
                        "entry": selected,
                        "select-page": select_page,
                    },
                    headers={"HX-Request": "true"},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.context["selected_count"], expected_count
                )
                self.assertNotContains(response, "<html")
                elements = ElementCollector(response.content.decode()).elements
                selection_form = next(
                    attrs
                    for tag, attrs in elements
                    if tag == "form" and attrs.get("id") == "entry-selection"
                )
                swap_targets = selection_form["hx-select-oob"].split(",")
                self.assertEqual(
                    swap_targets,
                    [
                        "#entry-selection-toolbar",
                        "#select-page",
                        "#entries-list-body",
                        "#entries-balance-inline",
                        "#entry-selection-actions",
                    ],
                )
                self.assertNotIn("#entries-scroll", swap_targets)
                self.assertNotIn("#entry-selection", swap_targets)
                ids = {attrs["id"] for tag, attrs in elements if "id" in attrs}
                for target in swap_targets:
                    self.assertIn(target.removeprefix("#"), ids)
                for tag, attrs in elements:
                    if '"update-selection"' in attrs.get("hx-vals", ""):
                        self.assertEqual(attrs["hx-swap"], "none")
                header = next(
                    attrs
                    for tag, attrs in elements
                    if tag == "input" and attrs.get("id") == "select-page"
                )
                self.assertEqual("checked" in header, expected_count == 2)
                buttons = {
                    attrs["name"]: attrs
                    for tag, attrs in elements
                    if tag == "button" and "name" in attrs
                }
                for action in ("calculate-balance", "remove-selected"):
                    self.assertEqual(
                        "disabled" in buttons[action], expected_count == 0
                    )
                self.assertEqual(
                    "disabled" in buttons["merge-selected"], expected_count < 2
                )
                for action in (
                    "change-account",
                    "change-asset",
                    "change-tags",
                    "change-country",
                ):
                    self.assertIn("disabled", buttons[action])
                checked = [
                    attrs
                    for tag, attrs in elements
                    if tag == "input"
                    and attrs.get("name") == "entry"
                    and "checked" in attrs
                ]
                self.assertEqual(len(checked), expected_count)
        self.assertEqual(self.book.entry_set.count(), 2)

    def test_selection_is_scoped_to_filtered_page(self):
        entries = [
            self.factory.make_entry(
                book=self.book,
                account=self.account,
                who=self.user,
                what=f"Entry {index}",
                country="US",
            )
            for index in range(3)
        ]
        excluded = self.factory.make_entry(
            book=self.book, who=self.user, country="AR"
        )
        private = self.factory.make_entry()
        self.client.force_login(self.user)
        url = (
            reverse("entries", args=[self.book.slug])
            + "?country=US&page_size=1&page=2"
        )
        response = self.client.post(
            url,
            {
                "update-selection": "change",
                "entry": [entry.pk for entry in entries]
                + [excluded.pk, private.pk],
            },
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.context["selected_ids"], {entries[1].pk})
        self.assertEqual(response.context["entries"].number, 2)
        self.assertEqual(response.context["filters"]["country"], "US")
        self.assertNotContains(response, private.what)
        elements = ElementCollector(response.content.decode()).elements
        for tag, attrs in elements:
            if tag == "input" and attrs.get("name") == "entry":
                self.assertEqual(attrs["hx-post"], url)
        response = self.client.post(
            url,
            {"update-selection": "page", "select-page": "all"},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.context["selected_ids"], {entries[1].pk})
        response = self.client.post(
            url,
            {"update-selection": "change", "entry": "invalid"},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.book.entry_set.count(), 4)

    def test_selection_keeps_targets_and_enables_only_valid_changes(self):
        entry = self.factory.make_entry(
            book=self.book, account=self.account, who=self.user
        )
        original_tags = entry.tags
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("entries", args=[self.book.slug]),
            {
                "update-selection": "change",
                "entry": [entry.pk],
                "account-target": self.account.pk,
                "tags-target": TAGS[0],
            },
            headers={"HX-Request": "true"},
        )
        self.assertIs(response.context["cannot_change_account"], False)
        self.assertIs(response.context["cannot_change_tags"], False)
        self.assertIs(response.context["cannot_change_country"], True)
        self.assertIs(response.context["cannot_change_asset"], True)
        self.assertEqual(
            response.context["edit_account_form"]["target"].value(),
            str(self.account.pk),
        )
        self.assertEqual(
            response.context["edit_tags_form"]["target"].value(), TAGS[0]
        )
        elements = ElementCollector(response.content.decode()).elements
        changes = next(
            attrs
            for tag, attrs in elements
            if tag == "div" and attrs.get("id") == "entry-changes"
        )
        self.assertEqual(
            changes["hx-post"], reverse("entries", args=[self.book.slug])
        )
        self.assertEqual(changes["hx-trigger"], "change")
        self.assertEqual(changes["hx-target"], "#entry-selection")
        entry.refresh_from_db()
        self.assertEqual(entry.account_id, self.account.pk)
        self.assertEqual(entry.tags, original_tags)
        self.assertEqual(self.book.entry_set.count(), 1)

    def test_search_clear_links_and_fields_preserve_other_filters(self):
        self.client.force_login(self.user)
        url = reverse("entries", args=[self.book.slug])
        response = self.client.get(
            url,
            {
                "q": "Coffee",
                "when": "2026-11-06",
                "tag": TAGS[0],
                "country": "US",
                "page": 2,
            },
        )
        elements = ElementCollector(response.content.decode()).elements
        links = [
            parse_qs(urlsplit(attrs["href"]).query)
            for tag, attrs in elements
            if tag == "a" and "href" in attrs
        ]
        self.assertIn(
            {
                "when": ["2026-11-06"],
                "tag": [TAGS[0]],
                "country": ["US"],
                "page": ["2"],
            },
            links,
        )
        self.assertIn(
            {
                "q": ["Coffee"],
                "tag": [TAGS[0]],
                "country": ["US"],
                "page": ["2"],
            },
            links,
        )
        self.assertEqual(
            response.context["search_filters"],
            [("tag", TAGS[0]), ("country", "US"), ("page", "2")],
        )
        self.assertNotContains(response, "jquery")
        self.assertNotContains(response, "onclick=")
        clear_links = {
            attrs["id"]: attrs
            for tag, attrs in elements
            if tag == "a"
            and attrs.get("id") in {"clear-search-text", "clear-search-date"}
        }
        self.assertEqual(len(clear_links), 2)
        for link_id, attrs in clear_links.items():
            with self.subTest(link_id=link_id):
                self.assertEqual(attrs["hx-boost"], "true")
                self.assertEqual(attrs["hx-target"], "#content")
                self.assertEqual(attrs["hx-select"], "#content")
                self.assertEqual(attrs["hx-swap"], "outerHTML show:none")
                self.assertEqual(attrs["hx-sync"], "#content:replace")
                cleared = self.client.get(
                    url,
                    parse_qs(urlsplit(attrs["href"]).query),
                    headers={"HX-Request": "true", "HX-Boosted": "true"},
                )
                self.assertContains(cleared, 'id="content"', count=1)
                filters = cleared.context["filters"]
                self.assertEqual(filters["tags"], [TAGS[0]])
                self.assertEqual(filters["country"], "US")
                self.assertEqual(parse_qs(filters["qs"])["page"], ["2"])
                self.assertEqual(cleared.context["entries"].number, 1)
                if link_id == "clear-search-text":
                    self.assertIsNone(filters["q"])
                    self.assertEqual(filters["when"], date(2026, 11, 6))
                else:
                    self.assertEqual(filters["q"], "Coffee")
                    self.assertIsNone(filters["when"])

    def test_search_and_date_filters_combine_and_links_preserve_page(self):
        matching = [
            self.factory.make_entry(
                book=self.book,
                account=self.account,
                who=self.user,
                what=f"Coffee {index}",
                when=date(2026, 11, 6),
            )
            for index in range(2)
        ]
        self.factory.make_entry(
            book=self.book, who=self.user, what="Tea", when=date(2026, 11, 6)
        )
        self.factory.make_entry(
            book=self.book,
            who=self.user,
            what="Coffee old",
            when=date(2026, 11, 5),
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("entries", args=[self.book.slug]),
            {"q": "Coffee", "when": "2026-11-06", "page": 2, "page_size": 1},
        )
        self.assertEqual(response.context["entries"].paginator.count, 2)
        self.assertEqual(list(response.context["entries"]), [matching[1]])
        elements = ElementCollector(response.content.decode()).elements
        queries = [
            parse_qs(urlsplit(attrs["href"]).query)
            for tag, attrs in elements
            if tag == "a" and "href" in attrs
        ]
        self.assertIn(
            {
                "q": ["Coffee"],
                "when": ["2026-11-05"],
                "page": ["2"],
                "page_size": ["1"],
            },
            queries,
        )
        account_links = [
            query
            for query in queries
            if query.get("account") == [self.account.slug]
        ]
        self.assertGreater(len(account_links), 0)
        for query in account_links:
            self.assertEqual(query["page"], ["2"])
            self.assertEqual(query["q"], ["Coffee"])

    def test_active_filters_remove_one_value_and_preserve_other_filters(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("entries", args=[self.book.slug]),
            {
                "tag": TAGS[:2],
                "country": "US",
                "q": "Coffee",
                "page": 3,
                "page_size": 10,
            },
        )
        chips = {
            item["label"]: item for item in response.context["active_filters"]
        }
        tag_query = parse_qs(urlsplit(chips[f"Tag: {TAGS[0]}"]["href"]).query)
        self.assertEqual(
            tag_query,
            {
                "tag": [TAGS[1]],
                "country": ["US"],
                "q": ["Coffee"],
                "page": ["3"],
                "page_size": ["10"],
            },
        )
        country_query = parse_qs(urlsplit(chips["Country: US"]["href"]).query)
        self.assertEqual(country_query["tag"], TAGS[:2])
        self.assertNotIn("country", country_query)
        self.assertEqual(country_query["page"], ["3"])
        self.assertEqual(
            parse_qs(response.context["filters"]["qs"])["tag"], TAGS[:2]
        )


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
        params = {"country": "US", "include_tag": TAGS[:2], "page": "2"}
        qs = urlencode(params, doseq=True)
        response = self.client.get(
            reverse("remove-entry", args=[self.book.slug, entry.pk]),
            params,
        )
        self.assertEqual(response.context["book"], self.book)
        self.assertEqual(parse_qs(response.context["qs"]), parse_qs(qs))
        self.assertInHTML(
            f'<input type="hidden" name="entry" value="{entry.pk}">',
            response.content.decode(),
        )
        self.assertEqual(self.book.entry_set.count(), 1)
        remove_url = reverse("remove-entry", args=[self.book.slug])
        for action in ("no", "yes"):
            with self.subTest(action=action):
                response = self.client.post(
                    remove_url + "?" + qs, {action: "", "entry": [entry.pk]}
                )
                self.assertEqual(response.status_code, 302)
                self.assertEqual(
                    parse_qs(urlsplit(response["Location"]).query),
                    parse_qs(qs),
                )
                self.assertEqual(
                    self.book.entry_set.count(), int(action == "no")
                )
        private = self.factory.make_entry()
        response = self.client.post(
            remove_url, {"yes": "", "entry": [private.pk]}
        )
        self.assertEqual(response.status_code, 404)
        private.refresh_from_db()


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
