# -*- coding: utf-8 -*-

import operator
import re
from collections import defaultdict, OrderedDict
from datetime import date, timedelta
from decimal import Decimal
from functools import reduce

from django.contrib.auth.models import User
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MinValueValidator
from django.db import connection, models, transaction
from django.db.models.functions import TruncMonth, TruncYear
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils.text import slugify
from django.utils.timezone import now
from django_countries import countries

from gemcore.currencies import CURRENCIES


TAGS = [
    'bureaucracy',
    'car',
    'change',
    'children',
    'food',
    'fun',
    'health',
    'house',
    'maintenance',
    'other',
    'rent',
    'taxes',
    'transportation',
    'utilities',
    'work-ish',
    'imported',
    'trips',
]


class DryRunError(Exception):
    """Dry run requested."""


def month_year_iter(start, end):
    # Adapted from:
    # http://stackoverflow.com/questions/5734438/how-to-create-a-month-iterator
    ym_start = 12 * start.year + start.month - 1
    ym_end = 12 * end.year + end.month
    for ym in range(ym_start, ym_end):
        y, m = divmod(ym, 12)
        yield date(y, m + 1, 1)


class ParserConfig(models.Model):

    name = models.TextField(unique=True)
    country = models.CharField(max_length=2, choices=countries)
    date_format = models.CharField(max_length=128, default='%Y-%m-%d')
    decimal_point = models.CharField(max_length=1, default='.')
    thousands_sep = models.CharField(max_length=1, default=',')
    ignore_rows = models.PositiveSmallIntegerField(default=0)

    when = ArrayField(
        base_field=models.PositiveSmallIntegerField(),
        help_text='Indexes start at 0, comma separated list of naturals.',
    )
    what = ArrayField(
        base_field=models.PositiveSmallIntegerField(),
        help_text='Indexes start at 0, comma separated list of naturals.',
    )
    amount = ArrayField(
        base_field=models.PositiveSmallIntegerField(),
        size=2,
        help_text='Indexes start at 0, comma separated list of naturals.',
    )
    notes = ArrayField(
        base_field=models.PositiveSmallIntegerField(),
        default=list,
        blank=True,
        help_text='Indexes start at 0, comma separated list of naturals.',
    )
    defer_processing = ArrayField(
        base_field=models.CharField(max_length=256),
        default=list,
        blank=True,
        help_text='Indexes start at 0, comma separated list of strings.',
    )

    def __str__(self):
        return self.name


class Book(models.Model):

    name = models.CharField(max_length=256)
    slug = models.SlugField(unique=True)
    users = models.ManyToManyField(User)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        return super(Book, self).save(*args, **kwargs)

    def latest_entries(self):
        return self.entry_set.all().order_by('-when')[:5]

    def by_text(self, text):
        return self.entry_set.filter(
            models.Q(what__icontains=text) | models.Q(notes__icontains=text)
        )

    def accounts(self, entries=None):
        if entries is None:
            entries = self.entry_set.all()

        return (
            entries.order_by('account')
            .values_list('account__slug', flat=True)
            .distinct()
        )

    def countries(self, entries=None):
        if entries is None:
            entries = self.entry_set.all()

        if not entries:
            return {}

        entries = ', '.join(str(e.id) for e in entries)
        cursor = connection.cursor()
        cursor.execute(
            "SELECT gemcore_entry.country, COUNT(*) FROM gemcore_entry "
            "WHERE gemcore_entry.book_id = %s "
            "AND gemcore_entry.id IN (%s) "
            "GROUP BY gemcore_entry.country "
            "ORDER BY gemcore_entry.country ASC;" % (self.id, entries)
        )
        result = OrderedDict(cursor.fetchall())
        return result

    def currencies(self, entries=None):
        if entries is None:
            entries = self.entry_set.all()

        result = defaultdict(int)
        for d in entries.values_list('account__currency', flat=True):
            result[d] += 1
        return dict(result)

    def month_breakdown(self, entries=None):
        if entries is None:
            entries = self.entry_set.all()
        # Truncate to month and add to select list
        entries = entries.annotate(month=TruncMonth('when')).values('month')
        # Group By month and select the count of the grouping
        entries = entries.annotate(
            count=models.Count('id'), total=models.Sum('amount')
        )
        return entries

    def months(self, entries=None):
        breakdown = self.month_breakdown(entries)

        result = defaultdict(int)
        for i in breakdown:
            result[date(1900, i['month'].month, 1)] += i['count']

        return dict(result)

    def year_breakdown(self, entries=None):
        if entries is None:
            entries = self.entry_set.all()
        # Truncate to year and add to select list
        entries = entries.annotate(year=TruncYear('when')).values('year')
        # Group By year and select the count of the grouping
        entries = entries.annotate(
            count=models.Count('id'), total=models.Sum('amount')
        )
        return entries

    def years(self, entries=None):
        breakdown = self.year_breakdown(entries)

        result = defaultdict(int)
        for i in breakdown:
            result[i['year'].year] += i['count']

        return dict(result)

    def tags(self, entries=None):
        if entries is None:
            entries = self.entry_set.all()

        if not entries:
            return {}

        result = OrderedDict()
        for tag in TAGS:
            tag_count = entries.filter(tags__contains=[tag]).count()
            if tag_count:
                result[tag] = tag_count

        return result

    def who(self, entries=None):
        if entries is None:
            entries = self.entry_set.all()
        result = defaultdict(int)
        for d in entries.values_list('who__username', flat=True):
            result[d] += 1
        return dict(result)

    def calculate_balance(self, entries=None, start=None, end=None):
        if entries is None:
            entries = self.entry_set.all()

        if entries.count() == 0:
            return

        if not start:
            start = entries.earliest('when').when
        if not end:
            end = entries.latest('when').when

        # Range test (inclusive).
        assert start <= end
        entries = entries.filter(when__range=(start, end))
        totals = entries.values('is_income').annotate(models.Sum('amount'))

        assert len(totals) <= 2, totals

        result = {
            'start': start,
            'end': end,
            'result': Decimal(0),
            'income': Decimal(0),
            'expense': Decimal(0),
        }
        for t in totals:
            key = 'income' if t['is_income'] else 'expense'
            value = t['amount__sum']
            # grand-local result per type of entry
            result[key] += value

        result['result'] = result['income'] - result['expense']
        return result

    def balance(self, entries=None, start=None, end=None):
        result = self.calculate_balance(entries, start, end)
        if not result:
            return

        months = []
        last_month = None
        sanity_check = Decimal(0)
        for next_month in month_year_iter(result['start'], result['end']):
            if last_month is not None:
                end_of_month = next_month - timedelta(days=1)
                month_balance = self.calculate_balance(
                    entries, start=last_month, end=end_of_month
                )
                sanity_check += month_balance['result']
                months.append(month_balance)
            last_month = next_month

        month_balance = self.calculate_balance(entries, last_month, end)
        sanity_check += month_balance['result']
        months.append(month_balance)

        assert sanity_check == result['result']

        return {'complete': result, 'months': months}

    def breakdown(self, entries=None, start=None, end=None):
        result = self.calculate_balance(entries, start, end)
        return result

    def merge_entries(
        self, *entries, dry_run=False, when=None, who=None, what=None
    ):
        # validate some minimal consistency on entries
        if len(entries) < 2:
            raise ValueError(
                'Need at least 2 entries to merge (got %s).' % len(entries)
            )

        books = {e.book for e in entries}
        if len(books) != 1 or books.pop() != self:
            raise ValueError(
                'Can not merge entries outside this book (got %s).'
                % ', '.join(sorted(b.slug for b in books))
            )

        accounts = {e.account for e in entries}
        if len(accounts) != 1:
            raise ValueError(
                'Can not merge entries for different accounts (got %s).'
                % ', '.join(sorted(a.slug for a in accounts))
            )

        countries = {e.country for e in entries}
        if len(countries) != 1:
            raise ValueError(
                'Can not merge entries for different countries (got %s).'
                % ', '.join(sorted(countries))
            )

        # prepare data for new Entry
        master = entries[0]
        who = who if who is not None else master.who
        when = when if when is not None else master.when
        if what is None:
            what = ' | '.join(
                sorted(
                    set(
                        '%s %s$%s'
                        % (e.what, '+' if e.is_income else '-', e.amount)
                        for e in entries
                    )
                )
            )
        amount = sum(e.money for e in entries)
        tags = reduce(operator.add, [e.tags for e in entries])
        notes = '\n'.join(str(e) for e in entries)
        kwargs = dict(
            book=self,
            who=who,
            when=when,
            what=what,
            account=accounts.pop(),
            amount=abs(amount),
            is_income=amount > 0,
            tags=tags,
            country=countries.pop(),
            notes=notes,
        )

        try:
            with transaction.atomic():
                result = Entry.objects.create(**kwargs)
                Entry.objects.filter(id__in=[e.id for e in entries]).delete()
                if dry_run:
                    raise DryRunError()
        except DryRunError:
            pass

        return result


class AccountManager(models.Manager):
    def by_book(self, book, **kwargs):
        return self.filter(users__book=book, active=True, **kwargs).distinct()


class Account(models.Model):

    name = models.CharField(max_length=256)
    slug = models.SlugField(unique=True)
    users = models.ManyToManyField(User)
    currency = models.CharField(
        max_length=3, choices=[(c, c) for c in CURRENCIES]
    )
    parser_config = models.ForeignKey(
        ParserConfig, null=True, blank=True, on_delete=models.CASCADE
    )
    active = models.BooleanField(default=True)

    objects = AccountManager()

    class Meta:
        ordering = ('currency', 'name')

    def __str__(self):
        result = '%s %s' % (self.currency, self.name)
        if self.users.count() == 1:
            result += ' %s' % self.users.get().username
        return result

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        return super(Account, self).save(*args, **kwargs)

    def tags_for(self, value):
        tags = {}
        for i in self.tagregex_set.all():
            pattern = re.compile(i.regex)
            if pattern.match(value):
                tags[i.tag] = i.transfer
        return tags


class TagRegex(models.Model):

    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    regex = models.TextField()
    tag = models.CharField(max_length=256, choices=((t, t) for t in TAGS))
    transfer = models.ForeignKey(
        Account,
        related_name='transfers',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )

    class Meta:
        unique_together = ('account', 'regex', 'tag')


class Entry(models.Model):

    book = models.ForeignKey(Book, on_delete=models.CASCADE)
    who = models.ForeignKey(User, on_delete=models.CASCADE)
    when = models.DateField(default=date.today)
    what = models.TextField()
    account = models.ForeignKey(Account, on_delete=models.CASCADE)
    amount = models.DecimalField(
        decimal_places=2,
        max_digits=12,
        validators=[MinValueValidator(Decimal('0'))],
    )
    is_income = models.BooleanField(default=False, verbose_name='Income?')
    tags = ArrayField(
        base_field=models.CharField(
            choices=((i, i) for i in TAGS), max_length=256
        ),
        default=list,
    )
    country = models.CharField(max_length=2, choices=countries)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = (
            'book',
            'account',
            'when',
            'what',
            'amount',
            'is_income',
        )
        verbose_name_plural = 'Entries'

    def __str__(self):
        return '%s: %s %s%.2f %s%s' % (
            self.when.strftime('%Y-%m-%d'),
            self.what,
            '+' if self.is_income else '-',
            self.amount,
            self.account,
            ' | ' + self.notes if self.notes else '',
        )

    @property
    def money(self):
        return self.amount if self.is_income else -self.amount


class EntryHistory(models.Model):

    DELETE = 'delete'
    MERGE = 'merge'

    book_slug = models.TextField()
    who_username = models.TextField()
    when = models.TextField()
    what = models.TextField()
    account_slug = models.TextField()
    amount = models.TextField()
    is_income = models.BooleanField()
    tags = models.TextField()
    country_code = models.CharField(max_length=2, choices=countries)
    notes = models.TextField(blank=True)

    creation_date = models.DateTimeField(default=now)
    reason = models.CharField(
        max_length=256, choices=((i, i) for i in (DELETE, MERGE))
    )

    def __str__(self):
        return '%s: %s (%s%s %s, by %s on %s, %s)' % (
            self.book_slug,
            self.what,
            '+' if self.is_income else '-',
            self.amount,
            self.account_slug,
            self.who_username,
            self.when,
            self.tags,
        )


@receiver(pre_delete, sender=Entry)
def record_entry_history(sender, instance, **kwargs):
    EntryHistory.objects.create(
        book_slug=instance.book.slug,
        who_username=instance.who.username,
        when=instance.when.isoformat(),
        what=instance.what,
        account_slug=instance.account.slug,
        amount=str(instance.amount),
        is_income=instance.is_income,
        tags=', '.join(instance.tags),
        country_code=instance.country,
        notes=instance.notes,
        reason=EntryHistory.DELETE,
    )
