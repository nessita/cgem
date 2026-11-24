from datetime import date, timedelta
from decimal import Decimal, DecimalException, localcontext
from http.client import HTTPException
from urllib.error import URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from django.core.management.base import CommandError

CODE = "bcu"
URL = (
    "https://cotizaciones.bcu.gub.uy/wscotizaciones/servlet/"
    "awsbcucotizaciones"
)
SOAP_NAMESPACE = "http://schemas.xmlsoap.org/soap/envelope/"
BCU_NAMESPACE = "Cotiza"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
EXTENSION = "xml"


def date_ranges(start, end):
    while True:
        until = start + timedelta(days=min(30, (end - start).days))
        yield start, until
        if until == end:
            break
        start = until + timedelta(days=1)


def validate_options(currencies, target, values):
    if target != "USD" or not set(currencies) <= {"ARS", "UYU"}:
        raise CommandError("BCU supports ARS and UYU to USD only.")
    result = {}
    for value in values:
        currency, separator, code = value.partition("=")
        if (
            not separator
            or currency not in currencies
            or currency in result
            or not code.isascii()
            or not code.isdecimal()
            or len(code) > 4
            or not 1 <= int(code) <= 9999
        ):
            raise CommandError(
                "Specify each currency's BCU series once as CURRENCY=CODE."
            )
        result[currency] = int(code)
    if set(result) != set(currencies) or len(set(result.values())) != len(
        result
    ):
        raise CommandError("Each currency requires a distinct BCU series.")
    return result


def cache_key(series, target):
    # Existing audit files must remain usable after provider extraction.
    return "_".join(
        f"{currency}-{code}" for currency, code in sorted(series.items())
    )


def fetch(start, end, series, target):
    envelope = ElementTree.Element(f"{{{SOAP_NAMESPACE}}}Envelope")
    body = ElementTree.SubElement(envelope, f"{{{SOAP_NAMESPACE}}}Body")
    execute = ElementTree.SubElement(
        body, f"{{{BCU_NAMESPACE}}}wsbcucotizaciones.Execute"
    )
    entry = ElementTree.SubElement(execute, f"{{{BCU_NAMESPACE}}}Entrada")
    currencies = ElementTree.SubElement(entry, f"{{{BCU_NAMESPACE}}}Moneda")
    for code in series.values():
        ElementTree.SubElement(currencies, f"{{{BCU_NAMESPACE}}}item").text = (
            str(code)
        )
    for name, value in (
        ("FechaDesde", start.isoformat()),
        ("FechaHasta", end.isoformat()),
        ("Grupo", "0"),
    ):
        ElementTree.SubElement(entry, f"{{{BCU_NAMESPACE}}}{name}").text = (
            value
        )
    request = Request(
        URL,
        data=ElementTree.tostring(envelope, encoding="utf-8"),
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": '"Cotizaaction/AWSBCUCOTIZACIONES.Execute"',
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except (URLError, OSError, HTTPException) as error:
        raise CommandError("Could not fetch BCU quotations.") from error
    if len(payload) > MAX_RESPONSE_BYTES:
        raise CommandError("BCU response exceeds the quotation size limit.")
    return payload


def positive_decimal(value):
    result = Decimal(value)
    if not result.is_finite() or result <= 0:
        raise ValueError("A quotation must be finite and positive.")
    return result


def normalize_quotation(fields, currency, code, start, end, target):
    quoted_date = date.fromisoformat(fields["Fecha"])
    expected_iso = {"USD", "DLS."} if currency == "UYU" else {currency}
    if (
        not start <= quoted_date <= end
        or fields["CodigoISO"] not in expected_iso
    ):
        raise ValueError("Unexpected date or quotation currency.")
    values = {}
    with localcontext() as context:
        context.prec = 50
        if currency == "UYU":
            # Inverting a quote reverses its buying and selling sides.
            buy = positive_decimal(fields["TCC"])
            sell = positive_decimal(fields["TCV"])
            if buy > sell:
                raise ValueError("Invalid BCU buying/selling spread.")
            values = {"buy": 1 / sell, "sell": 1 / buy}
        else:
            # BCU's local TCC/TCV values are not ARS/USD quotations.
            reference = positive_decimal(fields["ArbAct"])
            direction = fields["FormaArbitrar"]
            if direction == "0":
                reference = 1 / reference
            elif direction != "1":
                raise ValueError("Unsupported BCU quotation direction.")
            values["reference"] = reference
    return {
        "date": quoted_date,
        "from_currency": currency,
        "to_currency": target,
        "series": str(code),
        **values,
    }


def parse(payload, series, start, end, target):
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError:
        raise CommandError("BCU returned invalid XML.") from None
    if root.find(f".//{{{SOAP_NAMESPACE}}}Fault") is not None:
        raise CommandError("BCU returned a SOAP fault.")
    status = root.find(".//{*}respuestastatus/{*}codigoerror")
    code = (status.text or "").strip() if status is not None else None
    if code == "106":
        raise CommandError(
            "BCU is updating quotation data (106); try again later."
        )
    if code not in {"0", "100"}:
        raise CommandError("BCU did not return a successful quotation status.")
    if code == "100":
        return [], 0
    collection = root.find(".//{*}datoscotizaciones")
    if collection is None:
        raise CommandError("BCU response has no quotation collection.")
    currencies = {code: currency for currency, code in series.items()}
    quotations, invalid = [], 0
    for row in collection:
        fields = {
            child.tag.rsplit("}", 1)[-1]: (child.text or "").strip()
            for child in row
        }
        try:
            code = int(fields["Moneda"])
            currency = currencies[code]
            quotations.append(
                normalize_quotation(fields, currency, code, start, end, target)
            )
        except (KeyError, ValueError, DecimalException):
            invalid += 1
    return quotations, invalid
