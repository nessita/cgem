import json
from datetime import date
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import URLError
from xml.etree import ElementTree

from django.contrib.admin import AdminSite
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, transaction
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from gemrates.admin import ExchangeRateAdmin
from gemrates.management.helpers import cache_path, parse_response
from gemrates.models import ExchangeRate
from gemrates.providers import PROVIDERS, bcu
from gemrates.providers.bcu import MAX_RESPONSE_BYTES


def bcu_response(*rows, error=0):
    root = ElementTree.fromstring(
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"'
        '><soap:Body><wsbcucotizaciones.ExecuteResponse xmlns="Cotiza">'
        "<Salida><respuestastatus><codigoerror>"
        f"{error}</codigoerror></respuestastatus><datoscotizaciones />"
        "</Salida></wsbcucotizaciones.ExecuteResponse></soap:Body>"
        "</soap:Envelope>"
    )
    collection = root.find(".//{*}datoscotizaciones")
    for fields in rows:
        row = ElementTree.SubElement(
            collection, "{Cotiza}datoscotizaciones.dato"
        )
        for name, value in fields.items():
            ElementTree.SubElement(row, f"{{Cotiza}}{name}").text = str(value)
    return BytesIO(ElementTree.tostring(root))


def sample_provider():
    return SimpleNamespace(
        CODE="sample",
        URL="https://rates.example/",
        EXTENSION="json",
        MAX_RESPONSE_BYTES=4096,
        validate_options=lambda currencies, target, values: {
            currency: "daily" for currency in currencies
        },
        date_ranges=lambda start, end: [(start, end)],
        cache_key=lambda series, target: f"sample_EUR_{target}_daily",
        fetch=Mock(return_value=b'{"rate": "0.85"}'),
        parse=lambda payload, series, start, end, target: (
            [
                {
                    "date": start,
                    "from_currency": "EUR",
                    "to_currency": target,
                    "series": "daily",
                    "reference": Decimal(json.loads(payload)["rate"]),
                }
            ],
            0,
        ),
    )


class ExchangeRateAdminTestCase(SimpleTestCase):
    def test_admin_uses_the_selected_rate_in_both_directions(self):
        model_admin = ExchangeRateAdmin(ExchangeRate, AdminSite())
        quote = ExchangeRate(
            from_currency="UYU",
            to_currency="USD",
            buy=Decimal("0.02"),
            sell=Decimal("0.04"),
            reference=Decimal("0.024883049667"),
        )
        self.assertEqual(model_admin.conversion_rate(quote), "0.025")
        self.assertEqual(model_admin.inverse_rate(quote), "40.188")
        self.assertEqual(quote.rate, Decimal("0.024883049667"))
        quote.reference = None
        self.assertEqual(model_admin.conversion_rate(quote), "0.030")
        self.assertEqual(model_admin.inverse_rate(quote), "33.333")


class ExchangeRateAdminViewTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(
            username="rates-admin"
        )

    def test_add_form_renders_without_quotations(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("admin:gemrates_exchangerate_add"), secure=True
        )
        self.assertContains(response, 'name="reference"')

    def test_invalid_rates_redisplay_form_errors(self):
        self.client.force_login(self.user)
        for reference in ("", "0"):
            with self.subTest(reference=reference):
                response = self.client.post(
                    reverse("admin:gemrates_exchangerate_add"),
                    {
                        "date": "2026-09-07",
                        "from_currency": "UYU",
                        "to_currency": "USD",
                        "source": "ine",
                        "series": "ebrou",
                        "reference": reference,
                    },
                    secure=True,
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(
                    "reference", response.context["adminform"].form.errors
                )
        self.assertEqual(ExchangeRate.objects.count(), 0)


class ProviderWorkflowTestCase(TestCase):
    def test_registered_provider_uses_shared_audit_cache_and_import(self):
        provider = sample_provider()
        self.assertNotIn(provider.CODE, PROVIDERS)
        PROVIDERS[provider.CODE] = provider
        self.addCleanup(PROVIDERS.pop, provider.CODE)
        options = {
            "provider": provider.CODE,
            "start": date(2026, 1, 2),
            "end": date(2026, 1, 2),
            "currencies": ["EUR"],
            "target": "GBP",
        }
        with TemporaryDirectory() as directory:
            call_command(
                "audit_exchange_rates",
                **options,
                output=Path(directory),
                delay=0,
                stdout=StringIO(),
            )
            report_path = next(Path(directory).glob("*_report.json"))
            report = json.loads(report_path.read_text())
            self.assertEqual(report["source"], "sample")
            self.assertEqual(report["target"], "GBP")
            self.assertEqual(report["currencies"]["EUR"]["observations"], 1)
            path = cache_path(
                directory,
                provider,
                {"EUR": "daily"},
                options["start"],
                options["end"],
                "GBP",
            )
            self.assertEqual(path.suffix, ".json")
            payload = path.read_bytes()
            call_command(
                "fetch_exchange_rates",
                **options,
                cache_dir=Path(directory),
                stdout=StringIO(),
            )
            quote = ExchangeRate.objects.get()
            self.assertEqual(quote.source, "sample")
            self.assertEqual(quote.series, "daily")
            self.assertEqual(quote.from_currency, "EUR")
            self.assertEqual(quote.to_currency, "GBP")
            self.assertEqual(quote.rate, Decimal("0.85"))
            self.assertEqual(path.read_bytes(), payload)
            provider.fetch.assert_called_once()


class ExchangeRateAuditTestCase(SimpleTestCase):
    def test_audit_resumes_and_reports_dates_without_database_access(self):
        first = {
            "Fecha": "2026-01-02",
            "Moneda": "500",
            "CodigoISO": "ARS",
            "ArbAct": "1000",
            "FormaArbitrar": "0",
        }
        with (
            TemporaryDirectory() as directory,
            patch(
                "gemrates.providers.bcu.urlopen",
                side_effect=[
                    bcu_response(first, first),
                    URLError("offline"),
                    bcu_response({**first, "Fecha": "2026-02-02"}),
                ],
            ) as fetch,
        ):
            options = {
                "provider": "bcu",
                "start": date(2026, 1, 1),
                "end": date(2026, 2, 2),
                "currencies": ["ARS"],
                "series": ["ARS=500"],
                "output": Path(directory),
                "delay": 0,
                "stdout": StringIO(),
            }
            self.assertRaisesMessage(
                CommandError,
                "remain cached",
                call_command,
                "audit_exchange_rates",
                **options,
            )
            self.assertEqual(len(list(Path(directory).glob("*.xml"))), 1)
            self.assertEqual(list(Path(directory).glob("*_report.json")), [])
            call_command("audit_exchange_rates", **options)
            self.assertEqual(fetch.call_count, 3)
            report_path = next(Path(directory).glob("*_report.json"))
            report = json.loads(report_path.read_text())
            ars = report["currencies"]["ARS"]
            self.assertEqual(ars["observations"], 2)
            self.assertEqual(ars["first_date"], "2026-01-02")
            self.assertEqual(ars["last_date"], "2026-02-02")
            self.assertIn("2026-01-01", ars["missing_weekdays"])
            self.assertNotIn("2026-01-02", ars["missing_weekdays"])
            self.assertIn("2026-01-03", ars["missing_weekends"])
            call_command("audit_exchange_rates", **options)
            self.assertEqual(fetch.call_count, 3)

    def test_audit_preserves_rejected_rows_and_revalidates_cached_responses(
        self,
    ):
        row = {
            "Fecha": "2026-01-02",
            "Moneda": "500",
            "CodigoISO": "ARS",
            "ArbAct": "1000",
            "FormaArbitrar": "0",
        }
        for rows in (
            [{**row, "CodigoISO": "EUR"}],
            [row, {**row, "ArbAct": "2000"}],
        ):
            with (
                self.subTest(rows=rows),
                TemporaryDirectory() as directory,
                patch(
                    "gemrates.providers.bcu.urlopen",
                    return_value=bcu_response(*rows),
                ) as fetch,
            ):
                for _ in range(2):
                    self.assertRaisesMessage(
                        CommandError,
                        "Response saved at",
                        call_command,
                        "audit_exchange_rates",
                        provider="bcu",
                        start=date(2026, 1, 1),
                        end=date(2026, 1, 31),
                        currencies=["ARS"],
                        series=["ARS=500"],
                        output=Path(directory),
                        delay=0,
                        stdout=StringIO(),
                    )
                    self.assertEqual(fetch.call_count, 1)
                paths = list(Path(directory).iterdir())
                self.assertEqual(len(paths), 1)
                self.assertEqual(paths[0].suffix, ".xml")
                root = ElementTree.fromstring(paths[0].read_bytes())
                self.assertEqual(
                    len(root.find(".//{*}datoscotizaciones")), len(rows)
                )

    def test_keep_going_reports_rejections_and_preserves_other_observations(
        self,
    ):
        row = {
            "Fecha": "2026-01-02",
            "Moneda": "500",
            "CodigoISO": "ARS",
            "ArbAct": "1000",
            "FormaArbitrar": "0",
        }
        with (
            TemporaryDirectory() as directory,
            patch(
                "gemrates.providers.bcu.urlopen",
                side_effect=[
                    bcu_response(
                        row,
                        {**row, "CodigoISO": "EUR"},
                        {**row, "Fecha": "2026-01-05"},
                        {
                            **row,
                            "Fecha": "2026-01-05",
                            "ArbAct": "2000",
                        },
                        {**row, "Fecha": "2026-01-05"},
                    ),
                    bcu_response({**row, "Fecha": "2026-02-02"}),
                ],
            ) as fetch,
        ):
            self.assertRaisesMessage(
                CommandError,
                "Audit finished; rejected batches: 1.",
                call_command,
                "audit_exchange_rates",
                provider="bcu",
                start=date(2026, 1, 1),
                end=date(2026, 2, 2),
                currencies=["ARS"],
                series=["ARS=500"],
                output=Path(directory),
                delay=0,
                keep_going=True,
                stdout=StringIO(),
                stderr=StringIO(),
            )
            self.assertEqual(fetch.call_count, 2)
            report_path = next(Path(directory).glob("*_report.json"))
            report = json.loads(report_path.read_text())
            ars = report["currencies"]["ARS"]
            self.assertEqual(ars["observations"], 2)
            self.assertEqual(ars["last_date"], "2026-02-02")
            self.assertIn("2026-01-05", ars["missing_weekdays"])
            self.assertNotIn("2026-01-02", ars["missing_weekdays"])
            (batch,) = report["rejected_batches"]
            self.assertEqual(batch["invalid_rows"], 1)
            self.assertEqual(
                batch["conflicting_dates"],
                [{"currency": "ARS", "date": "2026-01-05"}],
            )
            self.assertTrue(Path(batch["response"]).is_file())


class ExchangeRateTestCase(TestCase):
    quotation = {
        "date": date(2026, 1, 28),
        "from_currency": "ARS",
        "to_currency": "USD",
        "source": "bcu",
        "series": "500",
        "reference": Decimal("0.001"),
    }
    row = {
        "Fecha": "2026-01-28",
        "Moneda": "500",
        "CodigoISO": "ARS",
        "TCC": "0.04",
        "TCV": "0.05",
        "ArbAct": "1000",
        "FormaArbitrar": "0",
    }
    command_options = {
        "provider": "bcu",
        "start": date(2026, 1, 28),
        "end": date(2026, 1, 30),
        "currencies": ["ARS", "UYU"],
        "series": ["ARS=500", "UYU=2225"],
    }

    def test_decimal_quotes_and_midpoint_preserve_distinct_series(self):
        quote = ExchangeRate(
            **{**self.quotation, "reference": None},
            buy=Decimal("0.024390243902"),
            sell=Decimal("0.025000000001"),
        )
        quote.full_clean()
        quote.save()
        quote.refresh_from_db()
        self.assertEqual(quote.midpoint, Decimal("0.0246951219515"))
        other = ExchangeRate.objects.create(
            **{**self.quotation, "series": "501"}
        )
        self.assertIsNone(other.midpoint)
        self.assertEqual(ExchangeRate.objects.count(), 2)

    def test_midpoint_preserves_precision_at_quote_limits(self):
        for buy, sell, midpoint in (
            ("0.000000000001", "0.000000000002", "0.0000000000015"),
            (
                "99999999.999999999998",
                "99999999.999999999999",
                "99999999.9999999999985",
            ),
        ):
            with self.subTest(buy=buy, sell=sell):
                quote = ExchangeRate(
                    **{**self.quotation, "reference": None},
                    buy=Decimal(buy),
                    sell=Decimal(sell),
                )
                quote.full_clean()
                self.assertEqual(quote.midpoint, Decimal(midpoint))

    def test_rate_uses_reference_then_midpoint_without_queries(self):
        for buy, sell, reference, expected in (
            ("0.02", "0.04", None, "0.03"),
            ("0.02", "0.04", "0.5", "0.5"),
            (None, None, "0.001", "0.001"),
            ("0.02", None, "0.001", "0.001"),
            (None, "0.04", "0.001", "0.001"),
            (None, None, None, None),
        ):
            with (
                self.subTest(buy=buy, sell=sell, reference=reference),
                self.assertNumQueries(0),
            ):
                quote = ExchangeRate(
                    buy=Decimal(buy) if buy is not None else None,
                    sell=Decimal(sell) if sell is not None else None,
                    reference=(
                        Decimal(reference) if reference is not None else None
                    ),
                )
                self.assertEqual(
                    quote.rate,
                    Decimal(expected) if expected is not None else None,
                )
                if buy is None or sell is None:
                    self.assertIsNone(quote.midpoint)

    def test_model_validation_rejects_unusable_quotations(self):
        for changes, message in (
            ({"reference": None}, "Provide a reference rate"),
            (
                {"reference": None, "buy": Decimal("1")},
                "Provide a reference",
            ),
            ({"reference": Decimal("0")}, "Ensure this value"),
            ({"reference": Decimal("-1")}, "Ensure this value"),
            ({"reference": Decimal("1e-13")}, "Ensure this value"),
            (
                {"reference": Decimal("1.0000000000001")},
                "decimal places",
            ),
            ({"reference": Decimal("1e8")}, "digits"),
            ({"reference": Decimal("NaN")}, "decimal"),
            ({"reference": Decimal("Infinity")}, "decimal"),
            ({"buy": Decimal("2"), "sell": Decimal("1")}, "Selling rate"),
            ({"to_currency": "ARS"}, "Currencies must differ"),
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaisesMessage(ValidationError, message),
            ):
                ExchangeRate(**{**self.quotation, **changes}).full_clean()

    def test_database_constraints_protect_quote_integrity(self):
        for changes, constraint in (
            ({"reference": None}, "exchange_rate_has_quote"),
            ({"reference": Decimal("0")}, "exchange_rate_positive_quotes"),
            ({"reference": Decimal("-1")}, "exchange_rate_positive_quotes"),
            (
                {"buy": Decimal("2"), "sell": Decimal("1")},
                "exchange_rate_ordered_spread",
            ),
            ({"to_currency": "ARS"}, "exchange_rate_distinct_currencies"),
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaisesMessage(IntegrityError, constraint),
                transaction.atomic(),
            ):
                ExchangeRate.objects.create(**{**self.quotation, **changes})
        ExchangeRate.objects.create(**self.quotation)
        with (
            self.assertRaisesMessage(
                IntegrityError, "exchange_rate_unique_quote"
            ),
            transaction.atomic(),
        ):
            ExchangeRate.objects.create(**self.quotation)

    def test_import_preparation_rounds_and_validates_without_queries(self):
        quote = ExchangeRate(
            **{
                **self.quotation,
                "reference": Decimal("0.0010000000015"),
            }
        )
        options = {
            "series": {"ARS": 500},
            "start": date(2026, 1, 28),
            "end": date(2026, 1, 30),
            "target": "USD",
        }
        with self.assertNumQueries(0):
            quote.prepare_import(**options)
        self.assertEqual(quote.reference, Decimal("0.001000000002"))
        for overrides in (
            {"target": "EUR"},
            {"start": date(2026, 1, 29)},
            {"series": {"ARS": 501}},
            {"series": {"UYU": 2225}},
        ):
            with (
                self.subTest(overrides=overrides),
                self.assertNumQueries(0),
                self.assertRaisesMessage(
                    ValidationError, "Unexpected quotation scope"
                ),
            ):
                quote.prepare_import(**{**options, **overrides})

    def test_manager_import_rolls_back_creations_and_updates_together(self):
        original = ExchangeRate.objects.create(**self.quotation)
        replacement = ExchangeRate(
            **{**self.quotation, "reference": Decimal("0")}
        )
        new = ExchangeRate(**{**self.quotation, "date": date(2026, 1, 29)})
        with self.assertRaisesMessage(
            IntegrityError, "exchange_rate_positive_quotes"
        ):
            ExchangeRate.objects.import_quotations(
                {
                    (replacement.from_currency, replacement.date): replacement,
                    (new.from_currency, new.date): new,
                },
                source="bcu",
                target="USD",
                series={"ARS": 500},
                start=date(2026, 1, 28),
                end=date(2026, 1, 30),
                replace=True,
            )
        original.refresh_from_db()
        self.assertEqual(original.reference, self.quotation["reference"])
        self.assertEqual(ExchangeRate.objects.count(), 1)

    def test_import_preserves_quote_directions_and_reports_missing_dates(self):
        output = StringIO()
        with patch(
            "gemrates.providers.bcu.urlopen",
            return_value=bcu_response(
                self.row,
                {
                    **self.row,
                    "Fecha": "2026-01-29",
                    "ArbAct": "0.002",
                    "FormaArbitrar": "1",
                },
                {
                    **self.row,
                    "Moneda": "2225",
                    "CodigoISO": "DLS.",
                    "TCC": "40",
                    "TCV": "41",
                },
            ),
        ) as fetch:
            call_command(
                "fetch_exchange_rates", **self.command_options, stdout=output
            )
        ars = ExchangeRate.objects.get(
            date=date(2026, 1, 28), from_currency="ARS"
        )
        self.assertEqual(ars.reference, Decimal("0.001"))
        self.assertIsNone(ars.buy)
        self.assertIsNone(ars.sell)
        self.assertEqual(
            ExchangeRate.objects.get(date=date(2026, 1, 29)).reference,
            Decimal("0.002"),
        )
        uyu = ExchangeRate.objects.get(from_currency="UYU")
        self.assertEqual(uyu.buy, Decimal("0.024390243902"))
        self.assertEqual(uyu.sell, Decimal("0.025"))
        self.assertIn(
            "Imported 3; replaced 0; skipped 0; invalid 0; missing 3.",
            output.getvalue(),
        )
        self.assertIn("Missing ARS/USD dates", output.getvalue())
        request = fetch.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        xml = ElementTree.fromstring(request.data)
        self.assertEqual(xml.find(".//{*}FechaDesde").text, "2026-01-28")
        self.assertEqual(xml.find(".//{*}FechaHasta").text, "2026-01-30")
        self.assertEqual(
            [item.text for item in xml.findall(".//{*}Moneda/{*}item")],
            ["500", "2225"],
        )

    def test_cached_import_reuses_reviewed_quotes_without_network_access(self):
        with (
            TemporaryDirectory() as directory,
            patch("gemrates.providers.bcu.urlopen") as fetch,
        ):
            path = cache_path(
                directory,
                bcu,
                {"UYU": 2225, "ARS": 500},
                self.command_options["start"],
                self.command_options["end"],
            )
            self.assertEqual(
                path.name, "ARS-500_UYU-2225_2026-01-28_2026-01-30.xml"
            )
            payload = bcu_response(
                self.row,
                {
                    **self.row,
                    "Moneda": "2225",
                    "CodigoISO": "DLS.",
                    "TCC": "11.900000",
                    "TCV": "11.905000",
                },
            ).getvalue()
            path.write_bytes(payload)
            path.with_suffix(".backup.xml").write_bytes(b"original response")
            output = StringIO()
            call_command(
                "fetch_exchange_rates",
                **self.command_options,
                cache_dir=Path(directory),
                stdout=output,
            )
            self.assertIn("Imported 2;", output.getvalue())
            quote = ExchangeRate.objects.get(from_currency="UYU")
            self.assertEqual(quote.buy, Decimal("0.083998320034"))
            self.assertEqual(quote.sell, Decimal("0.084033613445"))
            original = ExchangeRate.objects.get(from_currency="ARS")
            replacement = payload.replace(b"1000", b"500")
            path.write_bytes(replacement)
            for replace, expected in (
                (False, Decimal("0.001")),
                (True, Decimal("0.002")),
            ):
                call_command(
                    "fetch_exchange_rates",
                    **self.command_options,
                    cache_dir=Path(directory),
                    replace=replace,
                    stdout=StringIO(),
                )
                original.refresh_from_db()
                self.assertEqual(original.reference, expected)
            self.assertEqual(path.read_bytes(), replacement)
            fetch.assert_not_called()

    def test_missing_or_unusable_cached_batches_save_nothing(self):
        for payload, message in (
            (None, "Could not read cached response"),
            (b"not XML", "invalid XML"),
            (b" " * (MAX_RESPONSE_BYTES + 1), "exceeds the size limit"),
        ):
            with (
                self.subTest(message=message),
                TemporaryDirectory() as directory,
                patch("gemrates.providers.bcu.urlopen") as fetch,
            ):
                series = {"ARS": 500, "UYU": 2225}
                first = cache_path(
                    directory,
                    bcu,
                    series,
                    date(2026, 1, 1),
                    date(2026, 1, 31),
                )
                first.write_bytes(bcu_response(self.row).getvalue())
                if payload is not None:
                    second = cache_path(
                        directory,
                        bcu,
                        series,
                        date(2026, 2, 1),
                        date(2026, 2, 2),
                    )
                    second.write_bytes(payload)
                self.assertRaisesMessage(
                    CommandError,
                    message,
                    call_command,
                    "fetch_exchange_rates",
                    **{
                        **self.command_options,
                        "start": date(2026, 1, 1),
                        "end": date(2026, 2, 2),
                    },
                    cache_dir=Path(directory),
                    stdout=StringIO(),
                )
                self.assertEqual(ExchangeRate.objects.count(), 0)
                fetch.assert_not_called()

    def test_reimports_preserve_series_and_require_replacement(self):
        original = ExchangeRate.objects.create(**self.quotation)
        other = ExchangeRate.objects.create(
            **{
                **self.quotation,
                "series": "501",
                "reference": Decimal("0.01"),
            }
        )
        with patch(
            "gemrates.providers.bcu.urlopen",
            side_effect=lambda *args, **kwargs: bcu_response(
                {**self.row, "ArbAct": "500"}
            ),
        ):
            output = StringIO()
            call_command(
                "fetch_exchange_rates", **self.command_options, stdout=output
            )
            original.refresh_from_db()
            self.assertEqual(original.reference, Decimal("0.001"))
            self.assertIn("skipped 1", output.getvalue())
            call_command(
                "fetch_exchange_rates",
                **self.command_options,
                replace=True,
                stdout=StringIO(),
            )
            original.refresh_from_db()
            self.assertEqual(original.reference, Decimal("0.002"))
            timestamp = original.updated_at
            output = StringIO()
            call_command(
                "fetch_exchange_rates",
                **self.command_options,
                replace=True,
                stdout=output,
            )
            original.refresh_from_db()
            self.assertEqual(original.updated_at, timestamp)
            self.assertIn("skipped 1", output.getvalue())
        other.refresh_from_db()
        self.assertEqual(other.reference, Decimal("0.01"))
        self.assertEqual(ExchangeRate.objects.count(), 2)

    def test_invalid_and_conflicting_rows_do_not_replace_stored_quotes(self):
        original = ExchangeRate.objects.create(**self.quotation)
        bad_rows = [
            {**self.row, "Fecha": "2026-01-29", **changes}
            for changes in (
                {"ArbAct": "NaN"},
                {"ArbAct": "Infinity"},
                {"ArbAct": "0"},
                {"ArbAct": "-1"},
                {"ArbAct": "1e-9999999"},
                {"FormaArbitrar": "9"},
                {"CodigoISO": "USD"},
                {"Moneda": "9999"},
                {"Fecha": "2026-02-01"},
            )
        ]
        output = StringIO()
        with (
            patch(
                "gemrates.providers.bcu.urlopen",
                return_value=bcu_response(
                    *bad_rows,
                    self.row,
                    {**self.row, "ArbAct": "500"},
                    {**self.row, "Fecha": "2026-01-30"},
                ),
            ),
            self.assertRaisesMessage(CommandError, "Invalid or conflicting"),
        ):
            call_command(
                "fetch_exchange_rates",
                **self.command_options,
                replace=True,
                stdout=output,
            )
        original.refresh_from_db()
        self.assertEqual(original.reference, Decimal("0.001"))
        self.assertEqual(ExchangeRate.objects.count(), 2)
        self.assertIn(
            "Imported 1; replaced 0; skipped 0; invalid 11; missing 4.",
            output.getvalue(),
        )

    def test_bcu_dollar_codes_are_normalized_and_other_currencies_rejected(
        self,
    ):
        quoted_date = date(2009, 12, 1)
        for code in ("DLS.", "USD", "EUR"):
            with self.subTest(code=code):
                payload = bcu_response(
                    {
                        "Fecha": quoted_date.isoformat(),
                        "Moneda": "2225",
                        "CodigoISO": code,
                        "TCC": "19.930000",
                        "TCV": "19.930000",
                        "ArbAct": "1.000000",
                        "FormaArbitrar": "0",
                    }
                ).getvalue()
                quotations, invalid = parse_response(
                    bcu,
                    payload,
                    {"UYU": 2225},
                    quoted_date,
                    quoted_date,
                    "USD",
                )
                if code == "EUR":
                    self.assertEqual((quotations, invalid), ([], 1))
                else:
                    self.assertEqual(invalid, 0)
                    self.assertEqual(len(quotations), 1)
                    quote = quotations[0]
                    self.assertEqual(quote.from_currency, "UYU")
                    self.assertEqual(quote.to_currency, "USD")
                    self.assertEqual(quote.buy, Decimal("0.050175614651"))
                    self.assertEqual(quote.sell, quote.buy)

    def test_network_and_provider_failures_save_nothing(self):
        for payload, message in (
            (b"not XML", "invalid XML"),
            (
                b'<Envelope xmlns="http://schemas.xmlsoap.org/soap/envelope/">'
                b"<Body><Fault /></Body></Envelope>",
                "SOAP fault",
            ),
            (
                bcu_response(error=107).getvalue(),
                "successful quotation status",
            ),
            (
                bcu_response(
                    {"Fecha": "", "Moneda": "0"}, error=106
                ).getvalue(),
                "BCU is updating quotation data (106)",
            ),
        ):
            with (
                self.subTest(message=message),
                patch(
                    "gemrates.providers.bcu.urlopen",
                    return_value=BytesIO(payload),
                ),
                self.assertRaisesMessage(CommandError, message),
            ):
                call_command(
                    "fetch_exchange_rates",
                    **self.command_options,
                    stdout=StringIO(),
                )
            self.assertEqual(ExchangeRate.objects.count(), 0)
        with (
            patch(
                "gemrates.providers.bcu.urlopen",
                side_effect=[
                    bcu_response({**self.row, "Fecha": "2026-01-01"}),
                    URLError("offline"),
                ],
            ) as fetch,
            self.assertRaisesMessage(CommandError, "Could not fetch BCU"),
        ):
            call_command(
                "fetch_exchange_rates",
                **{
                    **self.command_options,
                    "start": date(2026, 1, 1),
                    "end": date(2026, 2, 2),
                },
                stdout=StringIO(),
            )
        self.assertEqual(ExchangeRate.objects.count(), 0)
        ranges = []
        for call in fetch.call_args_list:
            xml = ElementTree.fromstring(call.args[0].data)
            ranges.append(
                (
                    xml.find(".//{*}FechaDesde").text,
                    xml.find(".//{*}FechaHasta").text,
                )
            )
        self.assertEqual(
            ranges,
            [("2026-01-01", "2026-01-31"), ("2026-02-01", "2026-02-02")],
        )

    def test_missing_publications_and_invalid_options_are_explicit(self):
        with patch(
            "gemrates.providers.bcu.urlopen",
            return_value=bcu_response(error=100),
        ):
            output = StringIO()
            call_command(
                "fetch_exchange_rates", **self.command_options, stdout=output
            )
        self.assertIn("missing 6", output.getvalue())
        with patch("gemrates.providers.bcu.urlopen") as fetch:
            for changes, message in (
                ({"end": date(2026, 1, 1)}, "Start date"),
                ({"series": ["ARS=500"]}, "distinct BCU series"),
                ({"series": ["ARS=500", "UYU=500"]}, "distinct BCU series"),
                ({"series": ["ARS=500", "UYU=bad"]}, "CURRENCY=CODE"),
            ):
                with (
                    self.subTest(changes=changes),
                    self.assertRaisesMessage(CommandError, message),
                ):
                    call_command(
                        "fetch_exchange_rates",
                        **{**self.command_options, **changes},
                        stdout=StringIO(),
                    )
            fetch.assert_not_called()

    def test_import_query_count_does_not_grow_with_quotations(self):
        rows = [self.row]
        with (
            patch(
                "gemrates.providers.bcu.urlopen",
                side_effect=lambda *args, **kwargs: bcu_response(*rows),
            ),
            CaptureQueriesContext(connection) as queries,
        ):
            call_command(
                "fetch_exchange_rates",
                **self.command_options,
                stdout=StringIO(),
            )
        rows.extend(
            {**self.row, "Fecha": f"2026-01-{day}"} for day in (29, 30)
        )
        with (
            patch(
                "gemrates.providers.bcu.urlopen",
                side_effect=lambda *args, **kwargs: bcu_response(*rows),
            ),
            self.assertNumQueries(len(queries)),
        ):
            call_command(
                "fetch_exchange_rates",
                **self.command_options,
                stdout=StringIO(),
            )
        self.assertEqual(ExchangeRate.objects.count(), 3)
