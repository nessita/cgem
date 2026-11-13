import inspect
import re
from datetime import date

from django import forms
from django.test import SimpleTestCase

from gemcore import forms as gemcore_forms
from gemcore.constants import TAGS
from gemcore.forms import (
    ISO_DATE_PATTERN,
    EntryForm,
    EntryMergeForm,
    ISODateField,
    ISODateInput,
)
from gemcore.tests.helpers import BaseTestCase, ElementCollector


class ISODateInputTestCase(SimpleTestCase):
    def render(self, value=None, **kwargs):
        html = ISODateInput(**kwargs).render("when", value)
        return html, ElementCollector(html).elements

    def test_renders_text_input_with_hidden_native_picker(self):
        html, elements = self.render(date(2026, 11, 6))

        (wrapper,) = [a for tag, a in elements if tag == "div"]
        self.assertIn("data-iso-date", wrapper)
        text = next(
            a for tag, a in elements if tag == "input" and a["type"] == "text"
        )
        picker = next(
            a for tag, a in elements if tag == "input" and a["type"] == "date"
        )
        self.assertEqual(text["type"], "text")
        self.assertEqual(text["name"], "when")
        self.assertEqual(text["value"], "2026-11-06")
        self.assertEqual(text["pattern"], ISO_DATE_PATTERN)
        self.assertEqual(text["placeholder"], "YYYY-MM-DD")
        self.assertEqual(text["autocomplete"], "off")
        # The native input lends its calendar only: it must never be
        # submitted, focused with the keyboard or announced.
        self.assertEqual(picker["type"], "date")
        self.assertNotIn("name", picker)
        self.assertNotIn("value", picker)
        self.assertEqual(picker["tabindex"], "-1")
        self.assertEqual(picker["aria-hidden"], "true")
        (button,) = [a for tag, a in elements if tag == "button"]
        self.assertEqual(button["type"], "button")
        self.assertEqual(button["aria-label"], "Choose date from calendar")
        self.assertNotIn("disabled", button)
        self.assertNotIn("onclick", html)
        self.assertNotIn("onchange", html)

    def test_value_is_iso_whatever_the_active_locale(self):
        value = date(2026, 11, 6)
        for language in ("en-us", "en-gb", "de", "es-ar"):
            with self.subTest(language=language), self.settings(
                LANGUAGE_CODE=language, USE_I18N=True
            ):
                html, elements = self.render(value)
                text = next(a for tag, a in elements if tag == "input")
                self.assertEqual(text["value"], "2026-11-06")
        # Guard the guard: a stock widget does follow the locale.
        with self.settings(LANGUAGE_CODE="en-gb", USE_I18N=True):
            self.assertEqual(
                forms.DateInput().format_value(value), "06/11/2026"
            )

    def test_format_argument_can_not_change_the_output(self):
        html, elements = self.render(date(2026, 11, 6), format="%d/%m/%Y")

        text = next(a for tag, a in elements if tag == "input")
        self.assertEqual(text["value"], "2026-11-06")

    def test_empty_and_invalid_values(self):
        for value, expected in ((None, None), ("", ""), ("nope", "nope")):
            with self.subTest(value=value):
                html, elements = self.render(value)
                text = next(a for tag, a in elements if tag == "input")
                self.assertEqual(text.get("value"), expected)

    def test_custom_attrs_extend_the_defaults(self):
        for state in ("disabled", "readonly"):
            with self.subTest(state=state):
                html, elements = self.render(attrs={"class": "x", state: True})

                text = next(a for tag, a in elements if tag == "input")
                self.assertEqual(text["class"], "x")
                self.assertEqual(text["pattern"], ISO_DATE_PATTERN)
                self.assertIn(state, text)
                (button,) = [a for tag, a in elements if tag == "button"]
                self.assertIn("disabled", button)

    def test_pattern_matches_only_zero_padded_iso_dates(self):
        for value, expected in (
            ("2026-11-06", True),
            ("2026-01-31", True),
            ("0999-12-01", True),
            ("2026-13-01", False),
            ("2026-00-10", False),
            ("2026-11-32", False),
            ("2026-11-00", False),
            ("2026-1-6", False),
            ("11/06/2026", False),
            ("06/11/2026", False),
            ("20261106", False),
            (" 2026-11-06", False),
        ):
            with self.subTest(value=value):
                match = re.fullmatch(ISO_DATE_PATTERN, value)
                self.assertIs(match is not None, expected)


class ISODateFieldTestCase(SimpleTestCase):
    def test_accepts_only_iso_dates(self):
        field = ISODateField()

        self.assertEqual(field.clean("2026-11-06"), date(2026, 11, 6))
        self.assertEqual(field.clean(" 2026-11-06 "), date(2026, 11, 6))
        for value in ("11/06/2026", "06/11/2026", "2026-13-45", "Nov 6 2026"):
            with (
                self.subTest(value=value),
                self.assertRaisesMessage(
                    forms.ValidationError, "Enter a valid date."
                ),
            ):
                field.clean(value)

    def test_input_formats_can_not_be_widened(self):
        field = ISODateField(input_formats=["%d/%m/%Y"])

        self.assertEqual(field.input_formats, ["%Y-%m-%d"])
        with self.assertRaisesMessage(
            forms.ValidationError, "Enter a valid date."
        ):
            field.clean("06/11/2026")

    def test_optional_field_accepts_empty_value(self):
        self.assertIsNone(ISODateField(required=False).clean(""))

    def test_uses_iso_date_input_by_default(self):
        self.assertIsInstance(ISODateField().widget, ISODateInput)

    def test_bound_field_renders_label_and_app_styles(self):
        form = EntryMergeForm(initial={"when": date(2026, 11, 6)})

        html = form["when"].as_field_group()

        elements = ElementCollector(html).elements
        text = next(a for tag, a in elements if tag == "input")
        label = next(a for tag, a in elements if tag == "label")
        self.assertEqual(label["for"], text["id"])
        self.assertEqual(text["value"], "2026-11-06")
        self.assertIn("required", text)
        self.assertIn("min-w-0", text["class"].split())
        self.assertIn("w-full", text["class"].split())

    def test_every_date_field_in_the_app_is_an_iso_date_field(self):
        checked = []
        for name, form_class in inspect.getmembers(
            gemcore_forms, inspect.isclass
        ):
            if not issubclass(form_class, forms.BaseForm):
                continue
            for field_name, field in getattr(
                form_class, "base_fields", {}
            ).items():
                if not isinstance(field, forms.DateField):
                    continue
                with self.subTest(form=name, field=field_name):
                    self.assertIsInstance(field, ISODateField)
                    self.assertIsInstance(field.widget, ISODateInput)
                    checked.append((name, field_name))
        self.assertTrue(checked)


class EntryFormTestCase(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = cls.factory.make_user(username="entry-form-user")
        cls.book = cls.factory.make_book(users=[cls.user])
        cls.account = cls.factory.make_account(users=[cls.user])

    def test_rejects_multiple_submitted_tags(self):
        data = {
            "who": self.user.id,
            "when": date.today().isoformat(),
            "what": "Entry with too many tags",
            "account": self.account.id,
            "amount": "10.00",
            "tags": TAGS[:2],
            "country": "AR",
        }

        with self.assertRaisesMessage(
            ValueError,
            "EntryForm expects exactly one tag.",
        ):
            EntryForm(book=self.book, data=data)

    def test_rejects_instances_with_multiple_tags(self):
        entry = self.factory.make_entry(
            book=self.book,
            account=self.account,
            who=self.user,
            tags=[TAGS[0]],
        )
        entry.tags = TAGS[:2]

        with self.assertRaisesMessage(
            ValueError,
            "Entry instances must not have multiple tags.",
        ):
            EntryForm(book=self.book, instance=entry)
