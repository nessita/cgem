from decimal import DecimalException
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import CommandError

from gemrates.models import ExchangeRate


def cache_path(directory, provider, series, start, end, target="USD"):
    key = provider.cache_key(series, target)
    return Path(directory) / f"{key}_{start}_{end}.{provider.EXTENSION}"


def load_response(
    provider, series, start, end, target, cache_dir=None, *, input_file=None
):
    if cache_dir is not None and input_file is not None:
        raise CommandError("Choose either --cache-dir or --input-file.")
    if cache_dir is None and input_file is None:
        return provider.fetch(start, end, series, target)
    path = (
        Path(input_file)
        if input_file is not None
        else cache_path(cache_dir, provider, series, start, end, target)
    )
    try:
        with path.open("rb") as response:
            payload = response.read(provider.MAX_RESPONSE_BYTES + 1)
    except OSError as error:
        raise CommandError(f"Could not read quotation file: {path}") from error
    if len(payload) > provider.MAX_RESPONSE_BYTES:
        raise CommandError(f"Quotation file exceeds the size limit: {path}")
    return payload


def parse_response(provider, payload, series, start, end, target):
    values, invalid = provider.parse(payload, series, start, end, target)
    quotations = []
    for fields in values:
        try:
            quotation = ExchangeRate(source=provider.CODE, **fields)
            quotation.prepare_import(
                series=series, start=start, end=end, target=target
            )
            quotations.append(quotation)
        except (KeyError, ValueError, DecimalException, ValidationError):
            invalid += 1
    return quotations, invalid


def index_quotations(quotations):
    unique, conflicts, invalid = {}, set(), 0
    for quotation in quotations:
        key = quotation.from_currency, quotation.date
        if key in conflicts:
            invalid += 1
        elif (
            key in unique
            and unique[key].quote_values != quotation.quote_values
        ):
            unique.pop(key)
            conflicts.add(key)
            invalid += 2
        else:
            unique[key] = quotation
    return unique, conflicts, invalid
