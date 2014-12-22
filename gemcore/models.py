# -*- coding: utf-8 -*-

from collections import defaultdict, OrderedDict
from datetime import datetime
from decimal import Decimal

from bitfield import BitField
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import connection, models
from django.utils.text import slugify
from django_countries import countries


CURRENCIES = [
    'ARS', 'EUR', 'USD', 'UYU', 'GBP',
]
TAGS = [  # order is IMPORTANT, do not re-order
    'bureaucracy',  # 1
    'car',  # 2
    'change',  # 4
    'food',  # 8
    'fun',  # 16
    'health',  # 32
    'house',  # 64
    'maintainance',  # 128
    'other',  # 256
    'rent',  # 512
    'taxes',  # 1024
    'travel',  # 2048
    'utilities',  # 4096
    'withdraw',  # 8192
    'imported',  # 16384
]


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

    def tags(self, entries=None):
        if entries is None:
            entries = self.entry_set.all()

        if not entries:
            return {}

        result = OrderedDict()
        for tag in TAGS:
            tag_count = entries.filter(tags=getattr(Entry.tags, tag)).count()
            if tag_count:
                result[tag] = tag_count

        return result

    def years(self, entries=None):
        if entries is None:
            entries = self.entry_set.all()

        if not entries:
            return {}

        result = OrderedDict()
        oldest = entries.earliest('when').when.year
        newest = entries.latest('when').when.year
        for year in range(oldest, newest + 1):
            year_count = entries.filter(when__year=year).count()
            if year_count:
                result[year] = year_count

        return result

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
            "ORDER BY gemcore_entry.country ASC;" % (self.id, entries))
        result = OrderedDict(cursor.fetchall())
        return result

    def accounts(self, entries=None):
        if entries is None:
            entries = self.entry_set.all()

        if not entries:
            return []

        return entries.order_by('account').values_list(
            'account__slug', flat=True).distinct()

    def who(self, entries=None):
        if entries is None:
            entries = self.entry_set.all()
        result = defaultdict(int)
        for d in entries.values_list('who__username', flat=True):
            result[d] += 1
        return dict(result)


class Account(models.Model):

    name = models.CharField(max_length=256)
    slug = models.SlugField(unique=True)
    users = models.ManyToManyField(User)
    currency_code = models.CharField(
        max_length=3, choices=[(c, c) for c in CURRENCIES])

    class Meta:
        ordering = ('currency_code', 'name')

    def __str__(self):
        if self.users.count() == 1:
            result = '%s %s %s' % (
                self.currency_code, self.users.get().username, self.name)
        else:
            result = '%s shared %s' % (self.currency_code, self.name)
        return result

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        return super(Account, self).save(*args, **kwargs)

    def balance(self, book, start=None, end=None):
        entries = book.entry_set.filter(account=self)
        if start and end:
            assert start < end
            entries = entries.filter(when__range=(start, end))
        elif start:
            entries = entries.filter(when__gte=start)
            end = datetime.today()
        elif end:
            entries = entries.filter(when__lte=end)
            start = entries.earliest('when').when
        else:
            start = entries.earliest('when').when
            end = entries.latest('when').when

        totals = entries.values('is_income').annotate(models.Sum('amount'))
        assert len(totals) <= 2, totals

        result = {
            'start': start, 'end': end, 'result': Decimal(0),
            'income': Decimal(0), 'expense': Decimal(0),
        }
        for item in totals:
            if item['is_income']:
                result['income'] = item['amount__sum']
            else:
                result['expense'] = item['amount__sum']
        result['result'] = result['income'] - result['expense']
        return result


class Entry(models.Model):

    book = models.ForeignKey(Book)
    who = models.ForeignKey(User)
    when = models.DateField(default=datetime.today)
    what = models.TextField()
    account = models.ForeignKey(Account)
    amount = models.DecimalField(
        decimal_places=2, max_digits=12,
        validators=[MinValueValidator(Decimal('0.01'))])
    is_income = models.BooleanField(default=False, verbose_name='Income?')
    tags = BitField(flags=[(t.lower(), t) for t in TAGS])
    country = models.CharField(max_length=2, choices=countries)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = ('book', 'who', 'when', 'what', 'amount')
        verbose_name_plural = 'Entries'

    def __str__(self):
        return '%s (%s %s, by %s on %s)' % (
            self.what, self.amount, self.account, self.who, self.when)

    @property
    def currency(self):
        return self.account.currency_code
