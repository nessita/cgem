from decimal import ROUND_HALF_EVEN, Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils.timezone import now

from gemrates.constants import get_currency_choices

QUOTE_FIELDS = ("buy", "sell", "reference")
QUOTE_PRECISION = Decimal("1e-12")


class ExchangeRateManager(models.Manager):
    @transaction.atomic
    def import_quotations(
        self, incoming, source, target, series, start, end, replace=False
    ):
        created, updated, skipped = [], [], 0
        existing_rates = self.filter(
            source=source,
            to_currency=target,
            date__range=(start, end),
            from_currency__in=series,
            series__in=map(str, series.values()),
        ).select_for_update()
        existing = {
            (item.from_currency, item.date): item
            for item in existing_rates
            if item.series == str(series[item.from_currency])
        }
        for key, quotation in incoming.items():
            previous = existing.get(key)
            if previous is None:
                created.append(quotation)
            elif (
                not replace or previous.quote_values == quotation.quote_values
            ):
                skipped += 1
            else:
                for field in QUOTE_FIELDS:
                    setattr(previous, field, getattr(quotation, field))
                previous.updated_at = now()
                updated.append(previous)
        self.bulk_create(created)
        self.bulk_update(updated, (*QUOTE_FIELDS, "updated_at"))
        present = set(existing) | set(incoming)
        return len(created), len(updated), skipped, present


class ExchangeRate(models.Model):
    date = models.DateField()
    from_currency = models.CharField(
        max_length=3, choices=get_currency_choices
    )
    to_currency = models.CharField(max_length=3, choices=get_currency_choices)
    source = models.SlugField()
    series = models.SlugField()
    buy = models.DecimalField(
        max_digits=20,
        decimal_places=12,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("1e-12"))],
    )
    sell = models.DecimalField(
        max_digits=20,
        decimal_places=12,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("1e-12"))],
    )
    reference = models.DecimalField(
        max_digits=20,
        decimal_places=12,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("1e-12"))],
    )
    updated_at = models.DateTimeField(auto_now=True)

    objects = ExchangeRateManager()

    class Meta:
        ordering = ("date", "from_currency", "to_currency", "source", "series")
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "source",
                    "series",
                    "from_currency",
                    "to_currency",
                    "date",
                ),
                name="exchange_rate_unique_quote",
            ),
            models.CheckConstraint(
                condition=~models.Q(from_currency=models.F("to_currency")),
                name="exchange_rate_distinct_currencies",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(reference__isnull=False)
                    | models.Q(buy__isnull=False, sell__isnull=False)
                ),
                name="exchange_rate_has_quote",
            ),
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(buy__isnull=True)
                        | models.Q(buy__gt=0, buy__lt=Decimal("1e8"))
                    )
                    & (
                        models.Q(sell__isnull=True)
                        | models.Q(sell__gt=0, sell__lt=Decimal("1e8"))
                    )
                    & (
                        models.Q(reference__isnull=True)
                        | models.Q(
                            reference__gt=0, reference__lt=Decimal("1e8")
                        )
                    )
                ),
                name="exchange_rate_positive_quotes",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(buy__isnull=True)
                    | models.Q(sell__isnull=True)
                    | models.Q(buy__lte=models.F("sell"))
                ),
                name="exchange_rate_ordered_spread",
            ),
        ]

    def __str__(self):
        return (
            f"{self.date}: {self.from_currency}/{self.to_currency} "
            f"({self.source}/{self.series})"
        )

    def clean(self):
        super().clean()
        errors = {}
        if self.from_currency == self.to_currency:
            errors["to_currency"] = "Currencies must differ."
        if self.reference is None and (self.buy is None or self.sell is None):
            errors["reference"] = "Provide a reference rate or both quotes."
        if (
            isinstance(self.buy, Decimal)
            and self.buy.is_finite()
            and isinstance(self.sell, Decimal)
            and self.sell.is_finite()
            and self.buy > self.sell
        ):
            errors["sell"] = "Selling rate must not be below buying rate."
        if errors:
            raise ValidationError(errors)

    def prepare_import(self, *, series, start, end, target):
        if (
            not start <= self.date <= end
            or self.to_currency != target
            or self.from_currency not in series
            or self.series != str(series[self.from_currency])
        ):
            raise ValidationError("Unexpected quotation scope.")
        for field in QUOTE_FIELDS:
            value = getattr(self, field)
            if value is not None:
                setattr(
                    self,
                    field,
                    Decimal(value).quantize(
                        QUOTE_PRECISION, rounding=ROUND_HALF_EVEN
                    ),
                )
        # Database validation is batched by the importer, not per quotation.
        self.full_clean(validate_unique=False, validate_constraints=False)

    @property
    def quote_values(self):
        return tuple(getattr(self, field) for field in QUOTE_FIELDS)

    @property
    def midpoint(self):
        if self.buy is None or self.sell is None:
            return None
        return (self.buy + self.sell) / 2

    @property
    def rate(self):
        if (reference := self.reference) is not None:
            return reference
        return self.midpoint
