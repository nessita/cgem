import json
import math
import time
from datetime import date, timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from gemrates.constants import CURRENCIES
from gemrates.management.helpers import (
    cache_path,
    index_quotations,
    load_response,
    parse_response,
)
from gemrates.providers import PROVIDERS


def audit_quotations(quotations, invalid, *, keep_going=False):
    if invalid and not keep_going:
        raise CommandError(f"Provider returned {invalid} invalid quotations.")
    unique, conflicts, _ = index_quotations(quotations)
    if conflicts and not keep_going:
        raise CommandError("Provider returned conflicting quotations.")
    return unique, conflicts


class Command(BaseCommand):
    help = "Audit historical rate coverage without reading or writing the DB."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--provider", required=True, choices=PROVIDERS)
        parser.add_argument("--target", default="USD", choices=CURRENCIES)
        parser.add_argument("--start", required=True, type=date.fromisoformat)
        parser.add_argument("--end", required=True, type=date.fromisoformat)
        parser.add_argument(
            "--currencies", nargs="+", required=True, choices=CURRENCIES
        )
        parser.add_argument(
            "--series", nargs="+", default=[], metavar="CURRENCY=CODE"
        )
        parser.add_argument("--output", required=True, type=Path)
        parser.add_argument(
            "--input-file",
            type=Path,
            help="Read a downloaded provider file instead of fetching it.",
        )
        parser.add_argument("--delay", type=float, default=0.5)
        parser.add_argument(
            "--keep-going",
            action="store_true",
            help="Report rejected rows and continue auditing valid rows.",
        )

    def handle(self, *args, **options):
        start, end = options["start"], options["end"]
        if start > end:
            raise CommandError("Start date must not be after end date.")
        delay = options["delay"]
        if not math.isfinite(delay) or not 0 <= delay <= 60:
            raise CommandError("Delay must be between 0 and 60 seconds.")
        provider = PROVIDERS[options["provider"]]
        target = options["target"]
        series = provider.validate_options(
            options["currencies"], target, options["series"]
        )
        directory = options["output"]
        directory.mkdir(parents=True, exist_ok=True)
        prefix = provider.cache_key(series, target)
        present, rejected_batches = set(), []
        fetched, cached, loaded = 0, 0, 0
        ranges = list(provider.date_ranges(start, end))
        for index, (since, until) in enumerate(ranges, 1):
            path = cache_path(
                directory, provider, series, since, until, target
            )
            from_cache = path.exists()
            try:
                payload = load_response(
                    provider,
                    series,
                    since,
                    until,
                    target,
                    directory if from_cache else None,
                    input_file=(
                        options["input_file"] if not from_cache else None
                    ),
                )
                quotations, invalid = parse_response(
                    provider, payload, series, since, until, target
                )
                if from_cache:
                    cached += 1
                else:
                    # Preserve rejected rows for diagnosis without refetching.
                    partial = path.with_suffix(path.suffix + ".part")
                    partial.write_bytes(payload)
                    partial.rename(path)
                    if options["input_file"] is not None:
                        loaded += 1
                    else:
                        fetched += 1
                quotations, conflicts = audit_quotations(
                    quotations, invalid, keep_going=options["keep_going"]
                )
            except CommandError as error:
                response = (
                    f" Response saved at {path}." if path.exists() else ""
                )
                raise CommandError(
                    f"{since} to {until}: {error}{response} "
                    "Previous successful requests remain cached; rerun "
                    "with the same arguments to resume."
                ) from error
            present.update(quotations)
            if invalid or conflicts:
                rejected_batches.append(
                    {
                        "start": since.isoformat(),
                        "end": until.isoformat(),
                        "response": str(path.resolve()),
                        "invalid_rows": invalid,
                        "conflicting_dates": [
                            {"currency": currency, "date": day.isoformat()}
                            for currency, day in sorted(conflicts)
                        ],
                    }
                )
                self.stderr.write(
                    f"{since} to {until}: {invalid} invalid rows; "
                    f"{len(conflicts)} conflicting dates. See {path}"
                )
            if from_cache:
                origin = "cached"
            elif options["input_file"] is not None:
                origin = "file"
            else:
                origin = "fetched"
            self.stdout.write(
                f"[{index}/{len(ranges)}] {since} to {until}: "
                f"{len(quotations)} observations ({origin})"
            )
            self.stdout.flush()
            if not from_cache and index < len(ranges):
                time.sleep(delay)

        report = {
            "source": provider.CODE,
            "endpoint": provider.URL,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "target": target,
            "currencies": {},
            "rejected_batches": rejected_batches,
        }
        for currency, code in series.items():
            dates = sorted(day for cur, day in present if cur == currency)
            missing_weekdays, missing_weekends = [], []
            for offset in range((end - start).days + 1):
                day = start + timedelta(days=offset)
                if (currency, day) not in present:
                    missing = (
                        missing_weekdays
                        if day.weekday() < 5
                        else missing_weekends
                    )
                    missing.append(day.isoformat())
            report["currencies"][currency] = {
                "series": str(code),
                "observations": len(dates),
                "first_date": dates[0].isoformat() if dates else None,
                "last_date": dates[-1].isoformat() if dates else None,
                "missing_weekdays": missing_weekdays,
                "missing_weekends": missing_weekends,
            }
            self.stdout.write(
                f"{currency}/{target}: {len(dates)} observations; "
                f"{len(missing_weekdays)} weekdays without quotations; "
                f"{len(missing_weekends)} weekend days without quotations."
            )
        report_path = directory / f"{prefix}_{start}_{end}_report.json"
        partial = report_path.with_suffix(".json.part")
        partial.write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        partial.replace(report_path)
        self.stdout.write(
            f"Requests: {fetched} fetched; {cached} cached; "
            f"{loaded} loaded from file."
        )
        self.stdout.write(f"Report: {report_path}")
        self.stdout.write(
            "Weekday gaps can include holidays and days without trading; "
            "they are not automatically errors. No database changes made."
        )
        if rejected_batches:
            raise CommandError(
                f"Audit finished; rejected batches: {len(rejected_batches)}. "
                "Review the saved report "
                "and cached responses before importing."
            )
