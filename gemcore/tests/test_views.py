from datetime import UTC, date, datetime, timedelta, timezone
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.http import HttpResponse, HttpResponseRedirect
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse
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
from gemcore.tests.helpers import BaseTestCase

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


class BulkTestCaseMixin:
    action_name = ""
    action_btn = None

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

        assert self.action_btn is not None
        self.assertNotContains(response, self.action_btn)

    def test_button_shown_if_entries_available(self):
        for i in range(3):
            self.factory.make_entry(book=self.book, who=self.user)

        response = self.do_request()

        self.assertContains(response, self.action_btn)


class BulkRemoveTestCase(BulkTestCaseMixin, BaseTestCase):
    action_name = "remove-selected"
    action_btn = (
        '<button type="submit" class="btn btn-sm btn-default" '
        f'name="{action_name}">Remove</button>'
    )

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
            msg = '<li>%s<input type="hidden" name="entry" value="%s"/></li>'
            self.assertContains(response, msg % (str(e), e.id))

        self.assertEqual(self.book, response.context.get("book"))

        url = reverse("remove-entry", args=[self.book.slug])
        self.assertContains(
            response, '<form action="%s?" method="POST">' % url
        )


class BulkMergeTestCase(BulkTestCaseMixin, BaseTestCase):
    action_name = "merge-selected"
    action_btn = (
        '<button type="submit" class="btn btn-sm btn-default" '
        f'name="{action_name}">Merge</button>'
    )


class BulkChangeAccountTestCase(BulkTestCaseMixin, BaseTestCase):
    action_name = "change-account"
    action_btn = (
        '<button type="submit" class="btn btn-sm btn-default" '
        f'name="{action_name}">Change account</button>'
    )


class BulkChangeTagTestCase(BulkTestCaseMixin, BaseTestCase):
    action_name = "change-tags"
    action_btn = (
        '<button type="submit" class="btn btn-sm btn-default" '
        f'name="{action_name}">Change tag</button>'
    )

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
