from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.http import HttpResponse, HttpResponseRedirect
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse
from django.utils.html import escape
from django.utils.timezone import override
from django_htmx.middleware import HtmxMiddleware

from gemapi.serializers import EntryFilterSerializer, EntrySerializer
from gemcore.checks import check_entry_tags
from gemcore.constants import TAGS, ChoicesMixin
from gemcore.forms import (
    ISO_DATE_PATTERN,
    AccountTransferForm,
    BalanceForm,
    EntryForm,
    EntryMergeForm,
)
from gemcore.middleware import HtmxRedirectMiddleware
from gemcore.models import Asset, Entry, TagRegex
from gemcore.planning import get_planning_tags
from gemcore.tests.helpers import BaseTestCase, ElementCollector

DEFAULT_PASSWORD = "test"
PLANNING_ENTRY_TAGS = {
    "choices": [
        ("PAY", "Salary"),
        ("LEASE", "Rent"),
        ("YIELD", "Investments"),
        ("FX", "Currency change"),
        ("FD", "Food"),
        ("OTHER", "Other"),
    ],
    "default": "OTHER",
    "transfer": "FX",
    "planning": {"salary": "PAY", "rental": "LEASE", "investment": "YIELD"},
}


@override_settings(
    ENTRY_TAGS={
        "choices": [("MEAL", "Food"), ("MISC", "Other"), ("FX", "Change")],
        "default": "MISC",
        "transfer": "FX",
    }
)
class EntryTagConfigurationTestCase(SimpleTestCase):
    def test_valid_configuration(self):
        self.assertEqual(check_entry_tags(None), [])

    def test_invalid_configuration(self):
        valid = settings.ENTRY_TAGS
        for config, message in (
            (None, "must be a dictionary"),
            ([], "must be a dictionary"),
            ({}, "must contain nonempty category codes"),
            ({**valid, "choices": "MEAL"}, "must contain"),
            ({**valid, "choices": [("MEAL",)]}, "must contain"),
            ({**valid, "choices": [("", "Food")]}, "must contain"),
            ({**valid, "choices": [("MEAL", "")]}, "must contain"),
            ({**valid, "choices": [("X" * 257, "Food")]}, "must contain"),
            (
                {**valid, "choices": [("X", "Food"), ("X", "Other")]},
                "unique category codes",
            ),
            ({**valid, "default": "missing"}, "['default']"),
            ({**valid, "default": ["MISC"]}, "['default']"),
            ({**valid, "transfer": None}, "['transfer']"),
            ({**valid, "transfer": "missing"}, "['transfer']"),
            ({**valid, "default": "FX"}, "must be distinct"),
        ):
            with (
                self.subTest(config=config),
                override_settings(ENTRY_TAGS=config),
            ):
                errors = check_entry_tags(None)
                self.assertGreater(len(errors), 0)
                self.assertEqual(
                    {error.id for error in errors}, {"gemcore.E001"}
                )
                self.assertIn(message, errors[0].msg)


@override_settings(ENTRY_TAGS=PLANNING_ENTRY_TAGS)
class PlanningConfigurationTestCase(SimpleTestCase):
    def test_valid_mapping_uses_settings(self):
        mapping = {"salary": "PAY", "rental": "LEASE", "investment": "YIELD"}
        with override_settings(
            ENTRY_TAGS={**settings.ENTRY_TAGS, "planning": mapping}
        ):
            self.assertEqual(get_planning_tags(), mapping)
            self.assertEqual(check_entry_tags(None), [])

    def test_invalid_mappings_are_rejected(self):
        valid = {"salary": "PAY", "rental": "LEASE", "investment": "YIELD"}
        for mapping, message in (
            (None, "must map salary, rental, and investment"),
            ({}, "must map salary, rental, and investment"),
            ({"salary": "PAY"}, "must map salary, rental, and investment"),
            (
                {**valid, "extra": "PAY"},
                "must map salary, rental, and investment",
            ),
            ({**valid, "salary": "missing"}, "not in ENTRY_TAGS"),
            ({**valid, "investment": ["YIELD"]}, "not in ENTRY_TAGS"),
            ({**valid, "investment": "PAY"}, "must be distinct"),
            ({**valid, "investment": "FX"}, "currency-change one"),
        ):
            with (
                self.subTest(mapping=mapping),
                override_settings(
                    ENTRY_TAGS={**settings.ENTRY_TAGS, "planning": mapping}
                ),
                self.assertRaisesMessage(ImproperlyConfigured, message),
            ):
                get_planning_tags()
            if mapping is not None:
                with override_settings(
                    ENTRY_TAGS={**settings.ENTRY_TAGS, "planning": mapping}
                ):
                    errors = check_entry_tags(None)
                    self.assertIn(
                        message, " ".join(error.msg for error in errors)
                    )

    def test_system_checks_allow_optional_planning(self):
        with override_settings(
            ENTRY_TAGS={**settings.ENTRY_TAGS, "planning": None}
        ):
            self.assertEqual(check_entry_tags(None), [])

    def test_system_checks_reject_invalid_configuration(self):
        for config, message in (
            ([], "must be a dictionary"),
            ({}, "must contain nonempty category codes"),
            ({**PLANNING_ENTRY_TAGS, "choices": [("X",)]}, "must contain"),
            (
                {**PLANNING_ENTRY_TAGS, "choices": [("X", "A"), ("X", "B")]},
                "unique",
            ),
            ({**PLANNING_ENTRY_TAGS, "default": "missing"}, "['default']"),
            ({**PLANNING_ENTRY_TAGS, "transfer": "missing"}, "['transfer']"),
            (
                {
                    key: value
                    for key, value in PLANNING_ENTRY_TAGS.items()
                    if key != "transfer"
                },
                "['transfer']",
            ),
            ({**PLANNING_ENTRY_TAGS, "default": "FX"}, "must be distinct"),
            ({**PLANNING_ENTRY_TAGS, "planning": {}}, "must map"),
        ):
            with (
                self.subTest(config=config),
                override_settings(ENTRY_TAGS=config),
            ):
                errors = check_entry_tags(None)
                self.assertGreater(len(errors), 0)
                self.assertEqual(
                    {error.id for error in errors}, {"gemcore.E001"}
                )
                self.assertIn(message, errors[0].msg)

    def test_choices_follow_settings_overrides(self):
        first = settings.ENTRY_TAGS
        second = {
            "choices": [
                ("LUNCH", "Food"),
                ("IMPORT", "Other"),
                ("MOVE", "Change"),
            ],
            "default": "IMPORT",
            "transfer": "MOVE",
        }
        for config in (first, second):
            with (
                self.subTest(config=config),
                override_settings(ENTRY_TAGS=config),
            ):
                choices = config["choices"]
                codes = [code for code, label in choices]
                self.assertEqual(list(TAGS), codes)
                self.assertEqual(list(ChoicesMixin.TAG_CHOICES), choices)
                self.assertEqual(
                    list(Entry._meta.get_field("tags").base_field.choices),
                    choices,
                )
                self.assertEqual(
                    list(TagRegex._meta.get_field("tag").choices), choices
                )
                self.assertEqual(
                    list(EntrySerializer().fields["tags"].child.choices), codes
                )
                field = EntryFilterSerializer().fields["tag"].child
                self.assertEqual(list(field.choices), codes)
                for code, label in choices:
                    self.assertEqual(field.run_validation(label.lower()), code)


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
            EntryForm(book=self.book).fields["when"],
            EntryMergeForm.base_fields["when"],
            AccountTransferForm.base_fields["when"],
        )
        for field in fields:
            with self.subTest(field=field):
                self.assertEqual(field.widget.input_type, "text")
                self.assertEqual(
                    field.widget.attrs["placeholder"], "YYYY-MM-DD"
                )
                self.assertEqual(
                    field.widget.format_value(date(2026, 11, 3)),
                    "2026-11-03",
                )
                self.assertEqual(field.clean("2026-11-03"), date(2026, 11, 3))
            with (
                self.subTest(field=field, value="11/03/2026"),
                self.assertRaisesMessage(
                    ValidationError, str(field.error_messages["invalid"])
                ),
            ):
                field.clean("11/03/2026")

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
        self.assertEqual(entries[0].tags, [settings.ENTRY_TAGS["transfer"]])
        self.assertEqual(entries[0].amount, 10.00)
        self.assertEqual(entries[0].what, "Transfer test (source)")

        self.assertEqual(entries[1].tags, [settings.ENTRY_TAGS["transfer"]])
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

    def test_monthly_pagination_keeps_full_filtered_cumulative_totals(self):
        for month in (1, 2, 3):
            self.factory.make_entry(
                book=self.book,
                account=self.account,
                who=self.user,
                when=date(2026, month, 15),
                what="Coffee",
                amount=10,
                is_income=True,
                country="US",
                tags=[TAGS[0]],
            )
        other_currency = self.factory.make_account(
            users=[self.user], currency="EUR"
        )
        self.factory.make_entry(
            book=self.book,
            account=other_currency,
            who=self.user,
            when=date(2026, 2, 15),
            what="Coffee",
            amount=500,
            country="US",
            tags=[TAGS[0]],
        )
        self.factory.make_entry(
            book=self.book,
            account=self.account,
            who=self.user,
            when=date(2026, 2, 15),
            what="Coffee",
            amount=500,
            country="AR",
            tags=[TAGS[0]],
        )
        self.client.force_login(self.user)
        params = {
            "q": "Coffee",
            "country": "US",
            "tag": TAGS[0],
            "include_tag": TAGS[:2],
            "page_size": 1,
            "page": 2,
        }
        for scope in (
            {"account_slug": self.account.slug},
            {"currency": self.account.currency},
        ):
            with self.subTest(scope=scope):
                url = reverse(
                    "balance", kwargs={"book_slug": self.book.slug, **scope}
                )
                response = self.client.get(url, params)
                page = response.context["page_obj"]
                self.assertEqual(page.number, 2)
                self.assertEqual(page.paginator.count, 3)
                self.assertEqual(len(page), 1)
                self.assertEqual(page[0]["start"], date(2026, 2, 1))
                self.assertEqual(page[0]["result"], 10)
                self.assertEqual(page[0]["acc"], 20)
                self.assertEqual(
                    response.context["balance"]["complete"]["result"], 30
                )
                self.assertContains(
                    response, 'aria-label="Balance pages"', count=2
                )
                self.assertContains(response, 'id="filters-heading"', count=1)
                self.assertContains(response, 'id="tag-filter-heading"')
                self.assertNotContains(response, "2026 Mar</a>")
                elements = ElementCollector(response.content.decode()).elements
                next_page = next(
                    attrs["href"]
                    for tag, attrs in elements
                    if tag == "a" and attrs.get("aria-label") == "Next page"
                )
                expected = parse_qs(urlencode(params, doseq=True))
                expected["page"] = ["3"]
                self.assertEqual(parse_qs(urlsplit(next_page).query), expected)
                chip = next(
                    item
                    for item in response.context["active_filters"]
                    if item["name"] == "country"
                )
                expected["page"] = ["2"]
                expected.pop("country")
                self.assertEqual(
                    parse_qs(urlsplit(chip["href"]).query), expected
                )
                last_page = self.client.get(url, {**params, "page": 999})
                self.assertEqual(last_page.context["page_obj"].number, 3)
                self.assertEqual(
                    last_page.context["page_obj"][0]["start"],
                    date(2026, 1, 1),
                )
                self.assertEqual(last_page.context["page_obj"][0]["acc"], 10)

    def test_list_pagination_defaults_and_invalid_page_sizes_match(self):
        self.client.force_login(self.user)
        for name in ("entries", "balance"):
            for page_size in (None, "invalid", "0", "-2"):
                params = {"page": "invalid"}
                if page_size is not None:
                    params["page_size"] = page_size
                response = self.client.get(
                    reverse(name, args=[self.book.slug]), params
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.context["page_obj"].paginator.per_page,
                    2 if page_size == "-2" else 25,
                )
                self.assertEqual(response.context["page_obj"].number, 1)

    def test_balance_source_changes_preserve_filters_and_date_range(self):
        self.client.force_login(self.user)
        url = reverse("balance", args=[self.book.slug])
        params = {
            "q": "Coffee",
            "tag": TAGS[:2],
            "country": "US",
            "page": "2",
            "page_size": "1",
            "start": "2026-01-01",
            "end": "2026-03-31",
        }
        url += "?" + urlencode(params, doseq=True)
        response = self.client.get(url)
        for name in ("account_balance_form", "currency_balance_form"):
            form = response.context[name]
            self.assertEqual(form["start"].value(), date(2026, 1, 1))
            self.assertEqual(form["end"].value(), date(2026, 3, 31))
        elements = ElementCollector(response.content.decode()).elements
        self.assertEqual(
            [
                attrs["action"]
                for tag, attrs in elements
                if tag == "form" and attrs.get("method") == "POST"
            ],
            [url, url],
        )
        other_account = self.factory.make_account(
            users=[self.user], currency="EUR"
        )
        for action, source, scope in (
            (
                "get-account-balance",
                self.account.pk,
                {"account_slug": self.account.slug},
            ),
            (
                "get-currency-balance",
                self.account.currency,
                {"currency": self.account.currency},
            ),
        ):
            with self.subTest(action=action):
                for source_filters, compatible_filters in (
                    ({}, {}),
                    (
                        {"account": other_account.slug, "currency": "EUR"},
                        {},
                    ),
                    (
                        {
                            "account": self.account.slug,
                            "currency": self.account.currency,
                        },
                        {
                            "account": [self.account.slug],
                            "currency": [self.account.currency],
                        },
                    ),
                ):
                    source_url = url + "&" + urlencode(source_filters)
                    response = self.client.post(
                        source_url,
                        {
                            action: "",
                            "source": source,
                            "start": "2026-02-01",
                            "end": "",
                        },
                    )
                    self.assertEqual(response.status_code, 302)
                    destination = response["Location"]
                    self.assertEqual(
                        urlsplit(destination).path,
                        reverse(
                            "balance",
                            kwargs={"book_slug": self.book.slug, **scope},
                        ),
                    )
                    expected = parse_qs(urlencode(params, doseq=True))
                    expected.update(compatible_filters)
                    expected["start"] = ["2026-02-01"]
                    expected.pop("end")
                    self.assertEqual(
                        parse_qs(urlsplit(destination).query), expected
                    )


class BookPagesTestCase(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        tags = {"salary": "WORK", "rental": "RENT", "investment": "INVS"}
        available = {code for code, label in settings.ENTRY_TAGS["choices"]}
        choices = [
            (code, role.title())
            for role, code in tags.items()
            if code not in available
        ]
        cls.enterClassContext(
            override_settings(
                ENTRY_TAGS={
                    **settings.ENTRY_TAGS,
                    "choices": [*settings.ENTRY_TAGS["choices"], *choices],
                    "planning": tags,
                }
            )
        )

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = cls.factory.make_user()
        cls.book = cls.factory.make_book(users=[cls.user])
        cls.account = cls.factory.make_account(users=[cls.user])

    def test_book_pages_and_forms_render(self):
        self.client.force_login(self.user)
        navigation_pages = (
            "entries",
            "add-entry",
            "account-transfer",
            "balance",
            "planning",
            "load-from-file",
        )
        for name, args in (
            ("books", []),
            ("add-book", []),
            ("book", [self.book.slug]),
            ("entries", [self.book.slug]),
            ("add-entry", [self.book.slug]),
            ("balance", [self.book.slug]),
            ("planning", [self.book.slug]),
            ("load-from-file", [self.book.slug]),
            ("account-transfer", [self.book.slug]),
        ):
            with self.subTest(name=name):
                response = self.client.get(reverse(name, args=args))
                self.assertEqual(response.status_code, 200)
                if name not in navigation_pages:
                    continue
                html = response.content.decode()
                navigation = html.split(
                    f'<nav id="book-navigation-{self.book.pk}"', 1
                )[1].split("</nav>", 1)[0]
                links = [
                    attrs
                    for tag, attrs in ElementCollector(navigation).elements
                    if tag == "a"
                ]
                self.assertEqual(
                    [urlsplit(link["href"]).path for link in links],
                    [
                        reverse(page, args=[self.book.slug])
                        for page in navigation_pages
                    ],
                )
                self.assertEqual(
                    [
                        urlsplit(link["href"]).path
                        for link in links
                        if link.get("aria-current") == "page"
                    ],
                    [reverse(name, args=args)],
                )

    def test_sidebar_does_not_autofocus_and_counts_filter_options(self):
        self.client.force_login(self.user)
        asset = Asset.objects.create(name="Fund", since=date(2020, 1, 1))
        asset.users.add(self.user)
        self.factory.make_entry(
            book=self.book,
            account=self.account,
            who=self.user,
            asset=asset,
            tags=[TAGS[0]],
            when=date(2026, 11, 6),
        )
        for name in ("entries", "balance", "planning"):
            with self.subTest(page=name):
                response = self.client.get(
                    reverse(name, args=[self.book.slug]), {"year": 2026}
                )
                self.assertEqual(response.status_code, 200)
                elements = ElementCollector(response.content.decode()).elements
                search = next(
                    attrs
                    for tag, attrs in elements
                    if tag == "input" and attrs.get("id") == "search-text"
                )
                self.assertNotIn("autofocus", search)
                date_input = next(
                    attrs
                    for tag, attrs in elements
                    if tag == "input" and attrs.get("id") == "search-when"
                )
                self.assertEqual(date_input["type"], "text")
                self.assertEqual(date_input["placeholder"], "YYYY-MM-DD")
                for label in (
                    "Tags",
                    "Months",
                    "Years",
                    "Countries",
                    "People",
                    "Currencies",
                    "Assets",
                ):
                    self.assertContains(response, f">{label} (1)</summary>")

    def test_bottom_pagination_precedes_selection_actions(self):
        self.client.force_login(self.user)
        self.factory.make_entry(
            book=self.book,
            account=self.account,
            who=self.user,
        )
        response = self.client.get(reverse("entries", args=[self.book.slug]))
        html = response.content.decode()
        self.assertContains(response, 'aria-label="Entries pages"', count=2)
        self.assertLess(
            html.index('id="entries-scroll"'),
            html.rindex('aria-label="Entries pages"'),
        )
        self.assertLess(
            html.rindex('aria-label="Entries pages"'),
            html.index('id="entry-selection-actions"'),
        )

    def test_date_inputs_always_show_iso_dates(self):
        self.client.force_login(self.user)
        entry = self.factory.make_entry(
            book=self.book, account=self.account, who=self.user
        )
        for name, args, params, expected in (
            ("entries", [self.book.slug], {"when": "2026-11-06"}, ["when"]),
            ("planning", [self.book.slug], {"when": "2026-11-06"}, ["when"]),
            ("add-entry", [self.book.slug], {}, ["when"]),
            ("entry", [self.book.slug, entry.pk], {}, ["when"]),
            ("account-transfer", [self.book.slug], {}, ["when"]),
            (
                "balance",
                [self.book.slug],
                {"when": "2026-11-06"},
                ["when", "start", "end", "start", "end"],
            ),
        ):
            with self.subTest(name=name):
                response = self.client.get(reverse(name, args=args), params)
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                elements = ElementCollector(html).elements
                inputs = [attrs for tag, attrs in elements if tag == "input"]
                dates = [
                    attrs
                    for attrs in inputs
                    if attrs.get("name") in {"when", "start", "end"}
                    and attrs["type"] != "hidden"
                ]
                self.assertEqual([i["name"] for i in dates], expected)
                for attrs in dates:
                    self.assertEqual(attrs["type"], "text")
                    self.assertEqual(attrs["placeholder"], "YYYY-MM-DD")
                    self.assertEqual(attrs["pattern"], ISO_DATE_PATTERN)
                    if "value" in attrs:
                        self.assertRegex(attrs["value"], ISO_DATE_PATTERN)
                # Native date inputs exist only as nameless calendar helpers,
                # one per visible field.
                pickers = [i for i in inputs if i["type"] == "date"]
                self.assertEqual(len(pickers), len(dates))
                for attrs in pickers:
                    self.assertNotIn("name", attrs)
                self.assertEqual(html.count("data-iso-date"), len(dates))
                self.assertTrue(
                    any(
                        a.get("src", "").endswith("js/iso-date.js")
                        for t, a in elements
                        if t == "script"
                    )
                )
                self.assertNotContains(response, "onclick=")
                self.assertNotContains(response, "onchange=")

    def test_search_date_field_keeps_submitted_date(self):
        self.client.force_login(self.user)
        url = reverse("entries", args=[self.book.slug])
        for params, expected in (
            ({}, None),
            ({"when": "2026-11-06"}, "2026-11-06"),
        ):
            with self.subTest(params=params):
                response = self.client.get(url, params)
                elements = ElementCollector(response.content.decode()).elements
                (field,) = [
                    attrs
                    for tag, attrs in elements
                    if tag == "input" and attrs.get("name") == "when"
                ]
                self.assertEqual(field["id"], "search-when")
                self.assertEqual(field.get("value"), expected)
                self.assertNotIn("required", field)
                labels = [
                    attrs
                    for tag, attrs in elements
                    if tag == "label" and attrs.get("for") == "search-when"
                ]
                self.assertEqual(len(labels), 1)
                self.assertContains(response, ">Entry date</label>")

    def test_search_date_rejects_other_formats(self):
        self.client.force_login(self.user)
        url = reverse("entries", args=[self.book.slug])
        for value in ("11/06/2026", "06/11/2026", "2026-13-45"):
            with self.subTest(value=value):
                response = self.client.get(url, {"when": value})
                self.assertEqual(response.status_code, 400)

    def test_planning_navigation_follows_configuration(self):
        self.client.force_login(self.user)
        planning_path = reverse("planning", args=[self.book.slug])
        for name, args in (
            ("books", []),
            ("entries", [self.book.slug]),
        ):
            for params in ({}, {"year": "2026", "country": "US"}):
                for mapping in (settings.ENTRY_TAGS["planning"], None):
                    with (
                        self.subTest(
                            page=name, params=params, planning=mapping
                        ),
                        override_settings(
                            ENTRY_TAGS={
                                **settings.ENTRY_TAGS,
                                "planning": mapping,
                            }
                        ),
                    ):
                        response = self.client.get(
                            reverse(name, args=args), params
                        )
                        self.assertEqual(response.status_code, 200)
                        elements = ElementCollector(
                            response.content.decode()
                        ).elements
                        links = [
                            urlsplit(attrs["href"])
                            for tag, attrs in elements
                            if tag == "a"
                            and "href" in attrs
                            and urlsplit(attrs["href"]).path == planning_path
                        ]
                        self.assertEqual(len(links), int(mapping is not None))
                        for link in links:
                            self.assertEqual(
                                parse_qs(link.query),
                                {
                                    key: [value]
                                    for key, value in params.items()
                                },
                            )
                        self.assertContains(response, "New entry")

    def test_entry_filters_reject_invalid_values(self):
        self.client.force_login(self.user)
        for name in ("planning", "entries", "balance"):
            for params in (
                {"when": "2026-02-30"},
                {"start": "not-a-date"},
                {"end": "2026-02-30"},
                {"year": "not-a-year"},
                {"year": 0},
                {"year": 10000},
                {"month": "not-a-month"},
                {"start": "2026-12-01", "end": "2026-11-01"},
                {"is_income": "garbage"},
                {"asset_present": "garbage"},
                {"investment_related": "garbage"},
            ):
                with self.subTest(page=name, params=params):
                    response = self.client.get(
                        reverse(name, args=[self.book.slug]), params
                    )
                    self.assertEqual(response.status_code, 400)

    def test_boolean_and_any_tag_filters_return_matching_entries(self):
        self.client.force_login(self.user)
        asset = Asset.objects.create(name="Fund", since=date(2020, 1, 1))
        asset.users.add(self.user)
        salary = self.factory.make_entry(
            book=self.book,
            account=self.account,
            who=self.user,
            tags=["WORK"],
            is_income=True,
        )
        investment = self.factory.make_entry(
            book=self.book,
            account=self.account,
            who=self.user,
            tags=["INVS"],
            asset=asset,
            is_income=True,
        )
        expense = self.factory.make_entry(
            book=self.book,
            account=self.account,
            who=self.user,
            tags=["FD"],
            is_income=False,
        )
        all_ids = {salary.pk, investment.pk, expense.pk}
        for name, true_ids, false_ids in (
            ("is_income", {salary.pk, investment.pk}, {expense.pk}),
            ("asset_present", {investment.pk}, {salary.pk, expense.pk}),
            ("investment_related", {investment.pk}, {salary.pk, expense.pk}),
        ):
            for value, expected in (
                (None, None),
                ("", None),
                ("1", True),
                ("true", True),
                ("True", True),
                ("0", False),
                ("false", False),
                ("False", False),
            ):
                with self.subTest(name=name, value=value):
                    response = self.client.get(
                        reverse("entries", args=[self.book.slug]),
                        {} if value is None else {name: value},
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertIs(response.context["filters"][name], expected)
                    expected_ids = all_ids
                    if expected is not None:
                        expected_ids = true_ids if expected else false_ids
                    self.assertEqual(
                        {entry.pk for entry in response.context["entries"]},
                        expected_ids,
                    )
        response = self.client.get(
            reverse("entries", args=[self.book.slug]),
            {"tag_any": ["WORK", "INVS"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {entry.pk for entry in response.context["entries"]},
            {salary.pk, investment.pk},
        )

    def test_day_navigation_handles_calendar_boundaries(self):
        self.client.force_login(self.user)
        for when, unavailable in (
            (date.min, "when_prev"),
            (date.max, "when_next"),
        ):
            with self.subTest(when=when):
                response = self.client.get(
                    reverse("entries", args=[self.book.slug]),
                    {"when": when.isoformat()},
                )
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.context[unavailable])

    def test_planning_filters_require_configuration(self):
        self.client.force_login(self.user)
        for mapping in (None, {"salary": "missing"}):
            for name in ("entries", "balance"):
                for params in (
                    {},
                    {"planning_group": "income_total"},
                    {"investment_related": "1"},
                    {"investment_related": "0"},
                ):
                    with (
                        self.subTest(
                            mapping=mapping, page=name, params=params
                        ),
                        override_settings(
                            ENTRY_TAGS={
                                **settings.ENTRY_TAGS,
                                "planning": mapping,
                            }
                        ),
                    ):
                        response = self.client.get(
                            reverse(name, args=[self.book.slug]), params
                        )
                        self.assertEqual(
                            response.status_code, 400 if params else 200
                        )

    def test_unknown_planning_groups_are_rejected(self):
        self.client.force_login(self.user)
        for name in ("planning", "entries", "balance"):
            with self.subTest(page=name):
                response = self.client.get(
                    reverse(name, args=[self.book.slug]),
                    {"planning_group": "unknown"},
                )
                self.assertEqual(response.status_code, 400)

    def test_planning_period_displays_all_date_restrictions(self):
        self.client.force_login(self.user)
        for when, amount in (
            (date(2025, 11, 15), "1000"),
            (date(2026, 11, 1), "100"),
            (date(2026, 11, 15), "20"),
            (date(2026, 12, 15), "500"),
        ):
            self.factory.make_entry(
                book=self.book,
                account=self.account,
                who=self.user,
                when=when,
                amount=Decimal(amount),
                tags=["INVS"],
                is_income=True,
            )
        response = self.client.get(
            reverse("planning", args=[self.book.slug]),
            {
                "year": 2026,
                "month": "NOV",
                "start": "2026-11-10",
                "end": "2026-12-31",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["planning"]["USD"]["investment_net"]["amount"],
            Decimal("20"),
        )
        for text in (
            "Year: 2026",
            "Month: Nov",
            "From: " + "2026-11-10",
            "Until: " + "2026-12-31",
        ):
            self.assertContains(response, f"<span>{text}</span>", html=True)

    def test_planning_drilldown_accepts_category_named_untagged(self):
        self.client.force_login(self.user)
        with override_settings(
            ENTRY_TAGS={
                **settings.ENTRY_TAGS,
                "choices": [
                    *settings.ENTRY_TAGS["choices"],
                    ("UNTAGGED", "Uncategorized"),
                ],
            }
        ):
            entry = self.factory.make_entry(
                book=self.book,
                account=self.account,
                who=self.user,
                tags=["UNTAGGED"],
            )
            response = self.client.get(
                reverse("entries", args=[self.book.slug]),
                {"planning_group": "expenses", "planning_tag": "UNTAGGED"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["entries"]), [entry])

    def test_planning_warns_for_narrowed_scope_and_distinguishes_zero(self):
        self.client.force_login(self.user)
        url = reverse("planning", args=[self.book.slug])
        for tags, amount, is_income, country in (
            (["RENT"], "1500", True, "US"),
            (["FD"], "2000", False, "US"),
            (["FD"], "0", False, "BR"),
        ):
            self.factory.make_entry(
                book=self.book,
                account=self.account,
                who=self.user,
                when=date(2026, 11, 1),
                tags=tags,
                amount=Decimal(amount),
                is_income=is_income,
                country=country,
            )
        response = self.client.get(url, {"year": 2026, "currency": "USD"})
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.context["narrowed"], False)
        self.assertNotContains(response, "Showing a filtered selection")
        self.assertEqual(
            response.context["planning"]["USD"]["coverage_gap"]["amount"],
            Decimal("-500"),
        )
        response = self.client.get(
            url, {"tag": "RENT", "year": 2026, "currency": "USD"}
        )
        self.assertIs(response.context["narrowed"], True)
        self.assertContains(response, "Showing a filtered selection")
        self.assertContains(
            response, "No expense entries match these filters."
        )
        self.assertEqual(
            parse_qs(urlsplit(response.context["period_url"]).query),
            {"year": ["2026"], "currency": ["USD"]},
        )
        self.assertEqual(
            response.context["planning"]["USD"]["coverage_gap"]["amount"],
            Decimal("1500"),
        )
        response = self.client.get(url, {"country": "BR"})
        self.assertEqual(
            response.context["planning"]["USD"]["expenses"]["amount"], 0
        )
        self.assertNotContains(
            response, "No expense entries match these filters."
        )
        response = self.client.get(url, {"country": "CA"})
        self.assertContains(response, "No entries match these filters.")
        self.assertContains(response, 'aria-label="Filtered report scope"')

    def test_planning_year_redirects_to_query_filters(self):
        self.client.force_login(self.user)
        url = reverse("planning-year", args=[self.book.slug, 2026])
        response = self.client.get(
            url, {"year": 2025, "tag": TAGS[:2], "country": "US"}
        )
        self.assertEqual(response.status_code, 302)
        destination = urlsplit(response.url)
        self.assertEqual(
            destination.path, reverse("planning", args=[self.book.slug])
        )
        self.assertEqual(
            parse_qs(destination.query),
            {"year": ["2026"], "tag": TAGS[:2], "country": ["US"]},
        )
        response = self.client.get(response.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-labelledby="filters-heading"')
        for year in (0, 10000):
            with self.subTest(year=year):
                response = self.client.get(
                    reverse("planning-year", args=[self.book.slug, year])
                )
                self.assertEqual(response.status_code, 404)

    def test_planning_requires_book_access(self):
        url = reverse("planning", args=[self.book.slug])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.user)
        private = self.factory.make_book()
        for name, args in (
            ("planning", [private.slug]),
            ("planning-year", [private.slug, 2026]),
        ):
            with self.subTest(name=name):
                response = self.client.get(reverse(name, args=args))
                self.assertEqual(response.status_code, 404)
        response = self.client.post(url)
        self.assertEqual(response.status_code, 405)

    def test_planning_shows_configuration_errors_without_totals(self):
        self.client.force_login(self.user)
        for mapping in (None, {"salary": "missing"}):
            with (
                self.subTest(mapping=mapping),
                override_settings(
                    ENTRY_TAGS={**settings.ENTRY_TAGS, "planning": mapping}
                ),
            ):
                response = self.client.get(
                    reverse("planning", args=[self.book.slug])
                )
                self.assertEqual(response.status_code, 200)
                self.assertContains(
                    response, "Planning categories need configuration"
                )
                self.assertNotContains(
                    response, 'aria-label="Planning results"'
                )
                self.assertNotIn("planning", response.context)

    @override_settings(ENTRY_TAGS=PLANNING_ENTRY_TAGS)
    def test_planning_uses_configured_categories_in_totals_and_drilldowns(
        self,
    ):
        self.client.force_login(self.user)
        for tag, amount, income in (
            ("PAY", "3000", True),
            ("LEASE", "1500", True),
            ("YIELD", "400", True),
            ("YIELD", "50", False),
            ("FD", "1000", False),
            ("FX", "500", False),
            ("OTHER", "20", True),
        ):
            self.factory.make_entry(
                book=self.book,
                account=self.account,
                who=self.user,
                tags=[tag],
                amount=Decimal(amount),
                is_income=income,
            )
        response = self.client.get(reverse("planning", args=[self.book.slug]))
        self.assertEqual(response.status_code, 200)
        summary = response.context["planning"]["USD"]
        expected = {
            "income_salary": Decimal("3000"),
            "income_rental": Decimal("1500"),
            "investment_net": Decimal("350"),
            "non_salary_net": Decimal("1870"),
        }
        self.assertEqual(summary["coverage_gap"]["amount"], Decimal("870"))
        self.assertEqual(summary["ignored_change"]["amount"], Decimal("500"))
        for row in summary["overview_rows"] + summary["coverage_rows"]:
            if "url" not in row:
                continue
            group = parse_qs(urlsplit(row["url"]).query)["planning_group"][-1]
            if group not in expected:
                continue
            with self.subTest(group=group):
                self.assertEqual(row["amount"], expected[group])
                detail = self.client.get(row["url"])
                self.assertEqual(detail.status_code, 200)
                self.assertEqual(
                    sum(
                        (entry.money for entry in detail.context["entries"]),
                        Decimal("0"),
                    ),
                    expected[group],
                )

    def test_planning_drilldowns_match_totals_and_preserve_scope(self):
        self.client.force_login(self.user)
        asset = Asset.objects.create(name="Flat", since=date(2020, 1, 1))
        asset.users.add(self.user)
        for tags, amount, income, linked_asset in (
            (["FD"], "2000", False, None),
            (["WORK"], "3000", True, None),
            (["RENT"], "1500", True, asset),
            (["INVS"], "100", True, asset),
            (["INVS"], "500", False, asset),
            (["FD"], "25", False, asset),
            (["INVS"], "10", False, None),
            ([settings.ENTRY_TAGS["transfer"]], "900", False, None),
            ([settings.ENTRY_TAGS["default"]], "5", False, None),
            ([settings.ENTRY_TAGS["default"]], "20", True, None),
        ):
            self.factory.make_entry(
                book=self.book,
                account=self.account,
                who=self.user,
                when=date(2026, 11, 1),
                tags=tags,
                amount=Decimal(amount),
                is_income=income,
                asset=linked_asset,
                country="US",
            )
        self.factory.make_entry(
            book=self.book,
            account=self.account,
            who=self.user,
            when=date(2025, 11, 1),
            tags=["FD"],
            amount=Decimal("999"),
            country="US",
        )
        euro_account = self.factory.make_account(
            users=[self.user], currency="EUR"
        )
        self.factory.make_entry(
            book=self.book,
            account=euro_account,
            who=self.user,
            when=date(2026, 11, 1),
            tags=["FD"],
            amount=Decimal("7000"),
            country="US",
        )
        for params in (
            {"year": 2026, "country": "US"},
            {
                "year": 2026,
                "country": "US",
                "tag": ["FD"],
                "page": 2,
                "page_size": 1,
            },
        ):
            response = self.client.get(
                reverse("planning", args=[self.book.slug]), params
            )
            self.assertEqual(response.status_code, 200)
            summary = response.context["planning"]["USD"]
            if "tag" not in params:
                self.assertEqual(
                    summary["expenses"]["amount"], Decimal("2030")
                )
                self.assertEqual(
                    summary["income_total"]["amount"], Decimal("4620")
                )
                self.assertEqual(
                    summary["investment_outflows"]["amount"], Decimal("510")
                )
                self.assertEqual(
                    summary["investment_net"]["amount"], Decimal("-410")
                )
                self.assertEqual(
                    summary["non_salary_net"]["amount"], Decimal("1110")
                )
                self.assertEqual(
                    summary["coverage_gap"]["amount"], Decimal("-920")
                )
                self.assertEqual(
                    summary["net_result"]["amount"], Decimal("2080")
                )
                self.assertEqual(
                    summary["ignored_change"]["amount"], Decimal("900")
                )
            rows = summary["overview_rows"] + summary["coverage_rows"]
            rows += [
                row
                for section in summary["breakdowns"]
                for row in section["rows"]
            ]
            for row in rows:
                if "url" not in row:
                    continue
                with self.subTest(params=params, row=row["label"]):
                    query = parse_qs(urlsplit(row["url"]).query)
                    self.assertEqual(query["year"], ["2026"])
                    self.assertEqual(query["country"], ["US"])
                    self.assertNotIn("page", query)
                    self.assertNotIn("page_size", query)
                    if "tag" in params:
                        self.assertEqual(query["tag"], params["tag"])
                    detail = self.client.get(row["url"])
                    self.assertEqual(detail.status_code, 200)
                    self.assertEqual(
                        sum(
                            (
                                (
                                    entry.money
                                    if row.get("signed")
                                    else entry.amount
                                )
                                for entry in detail.context["entries"]
                            ),
                            Decimal("0"),
                        ),
                        row["amount"],
                    )

    def test_planning_nets_savings_movements_and_costs_without_assets(self):
        self.client.force_login(self.user)
        for tag, amount, income, month in (
            ("INVS", "10000", False, 1),
            ("INVS", "10500", True, 2),
            ("INVS", "50", False, 2),
            ("INVS", "60", False, 2),
            ("RENT", "1000", True, 2),
            (settings.ENTRY_TAGS["default"], "100", True, 2),
            ("WORK", "3000", True, 2),
            ("FD", "1000", False, 2),
        ):
            self.factory.make_entry(
                book=self.book,
                account=self.account,
                who=self.user,
                when=date(2026, month, 1),
                tags=[tag],
                amount=Decimal(amount),
                is_income=income,
            )
        url = reverse("planning", args=[self.book.slug])
        response = self.client.get(url, {"year": 2026})
        self.assertEqual(response.status_code, 200)
        summary = response.context["planning"]["USD"]
        self.assertEqual(summary["investment_net"]["amount"], Decimal("390"))
        self.assertEqual(summary["non_salary_net"]["amount"], Decimal("1490"))
        self.assertEqual(summary["expenses"]["amount"], Decimal("1000"))
        self.assertEqual(summary["coverage_gap"]["amount"], Decimal("490"))
        self.assertEqual(summary["net_result"]["amount"], Decimal("3490"))
        self.assertContains(response, "Net investment cash flow")
        self.assertContains(
            response,
            "Approximates investment income when those movements balance "
            "within the selected period.",
        )
        self.assertContains(
            response,
            "Asset breakdowns exclude entries without an assigned asset.",
        )
        for month, expected in (("jan", "-10000"), ("feb", "10390")):
            with self.subTest(month=month):
                response = self.client.get(url, {"year": 2026, "month": month})
                self.assertEqual(
                    response.context["planning"]["USD"]["investment_net"][
                        "amount"
                    ],
                    Decimal(expected),
                )

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
                    response,
                    '<caption class="sr-only">Monthly balance</caption>',
                    count=len(selected),
                    html=True,
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
                self.assertEqual(
                    attrs["hx-swap"], "outerHTML show:none focus-scroll:false"
                )
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
