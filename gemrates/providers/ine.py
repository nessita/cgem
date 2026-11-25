from datetime import date, datetime
from decimal import Decimal, DecimalException, localcontext
from http.client import HTTPException
from io import BytesIO
from urllib.error import URLError
from urllib.request import urlopen

from django.core.management.base import CommandError
from python_calamine import CalamineError, CalamineWorkbook

CODE = "ine"
URL = (
    "https://www5.ine.gub.uy/documents/Estad%C3%ADsticasecon%C3%B3micas/"
    "SERIES%20Y%20OTROS/Cotizaci%C3%B3n%20monedas/"
    "Cotizaci%C3%B3n%20monedas.xlsx"
)
EXTENSION = "xlsx"
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
SERIES = {"regular": "Dólar.USA", "ebrou": "Dólar.eBROU"}
MISSING_VALUES = (None, "", "..", "…")


def date_ranges(start, end):
    # The workbook contains the complete history in one download.
    yield start, end


def validate_options(currencies, target, values):
    if set(currencies) != {"UYU"} or target != "USD":
        raise CommandError("INE supports UYU to USD only.")
    if len(values) != 1 or values[0] not in {f"UYU={code}" for code in SERIES}:
        raise CommandError(
            "Specify UYU=regular or UYU=ebrou as the INE series."
        )
    return {"UYU": values[0].partition("=")[2]}


def cache_key(series, target):
    return f"ine_UYU-{series['UYU']}_{target}"


def fetch(start, end, series, target):
    try:
        with urlopen(URL, timeout=30) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except (URLError, OSError, HTTPException) as error:
        raise CommandError("Could not fetch INE quotations.") from error
    if len(payload) > MAX_RESPONSE_BYTES:
        raise CommandError("INE response exceeds the quotation size limit.")
    return payload


def quotation_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%d-%m-%Y").date()


def positive_decimal(value):
    # str(float) removes XLSX binary representation noise before inversion.
    result = Decimal(str(value))
    if not result.is_finite() or result <= 0:
        raise ValueError("A quotation must be finite and positive.")
    return result


def parse_rows(rows, code, start, end, target):
    header = next(rows, ())
    prefix = SERIES[code]
    required = ("Fecha", f"{prefix}.Compra", f"{prefix}.Venta")
    if any(header.count(name) != 1 for name in required):
        raise CommandError("INE workbook has unexpected quotation columns.")
    columns = [header.index(name) for name in required]
    quotations, invalid = [], 0
    for row in rows:
        if all(value in (None, "") for value in row):
            continue
        try:
            day, buy, sell = (
                row[column] if column < len(row) else None
                for column in columns
            )
            day = quotation_date(day)
            if not start <= day <= end:
                continue
            # Missing quotations must stay as gaps rather than invented rates.
            if buy in MISSING_VALUES and sell in MISSING_VALUES:
                continue
            buy, sell = positive_decimal(buy), positive_decimal(sell)
            if buy > sell:
                raise ValueError("Invalid INE buying/selling spread.")
            with localcontext() as context:
                context.prec = 50
                quotations.append(
                    {
                        "date": day,
                        "from_currency": "UYU",
                        "to_currency": target,
                        "series": code,
                        "buy": 1 / sell,
                        "sell": 1 / buy,
                    }
                )
        except (TypeError, ValueError, DecimalException):
            invalid += 1
    return quotations, invalid


def parse(payload, series, start, end, target):
    try:
        with CalamineWorkbook.from_filelike(BytesIO(payload)) as workbook:
            if "Fuente BROU" not in workbook.sheet_names:
                raise CommandError("INE workbook has no Fuente BROU sheet.")
            return parse_rows(
                workbook.get_sheet_by_name("Fuente BROU").iter_rows(),
                series["UYU"],
                start,
                end,
                target,
            )
    except CalamineError as error:
        raise CommandError("Could not read the INE workbook.") from error
