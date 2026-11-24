from datetime import date, timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from gemrates.constants import CURRENCIES
from gemrates.management.helpers import (
    index_quotations,
    load_response,
    parse_response,
)
from gemrates.models import ExchangeRate
from gemrates.providers import PROVIDERS


class Command(BaseCommand):
    help = "Import daily historical reference exchange rates."

    def add_arguments(self, parser):
        parser.add_argument("--provider", required=True, choices=PROVIDERS)
        parser.add_argument("--start", required=True, type=date.fromisoformat)
        parser.add_argument("--end", required=True, type=date.fromisoformat)
        parser.add_argument(
            "--currencies", nargs="+", required=True, choices=CURRENCIES
        )
        parser.add_argument("--target", default="USD", choices=CURRENCIES)
        parser.add_argument(
            "--series", nargs="+", default=[], metavar="CURRENCY=CODE"
        )
        parser.add_argument("--replace", action="store_true")
        parser.add_argument(
            "--cache-dir",
            type=Path,
            help="Read audited files without contacting the provider.",
        )

    def handle(self, *args, **options):
        start, end = options["start"], options["end"]
        if start > end:
            raise CommandError("Start date must not be after end date.")
        provider = PROVIDERS[options["provider"]]
        target = options["target"]
        series = provider.validate_options(
            options["currencies"], target, options["series"]
        )
        quotations, invalid = [], 0
        # Read every batch before writing so missing input saves nothing.
        for since, until in provider.date_ranges(start, end):
            payload = load_response(
                provider, series, since, until, target, options["cache_dir"]
            )
            batch, rejected = parse_response(
                provider, payload, series, since, until, target
            )
            quotations.extend(batch)
            invalid += rejected
        incoming, _, rejected = index_quotations(quotations)
        invalid += rejected
        try:
            created, updated, skipped, present = (
                ExchangeRate.objects.import_quotations(
                    incoming,
                    provider.CODE,
                    target,
                    series,
                    start,
                    end,
                    replace=options["replace"],
                )
            )
        except IntegrityError:
            raise CommandError(
                "The import conflicted with stored quotations; nothing saved. "
                "Check for a concurrent import and retry."
            ) from None
        missing_count = 0
        for currency in series:
            missing = [
                (start + timedelta(days=offset)).isoformat()
                for offset in range((end - start).days + 1)
                if (currency, start + timedelta(days=offset)) not in present
            ]
            missing_count += len(missing)
            if missing:
                self.stdout.write(
                    f"Missing {currency}/{target} dates (non-publication days "
                    f"included): {', '.join(missing)}"
                )
        self.stdout.write(
            f"Imported {created}; replaced {updated}; "
            f"skipped {skipped}; invalid {invalid}; missing {missing_count}."
        )
        if invalid:
            raise CommandError(
                "Invalid or conflicting quotations were rejected. "
                "Other valid quotations were imported."
            )
