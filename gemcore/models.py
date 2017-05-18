# -*- coding: utf-8 -*-

import operator
import re

from collections import defaultdict, OrderedDict
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import reduce

from bitfield import BitField
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import connection, models, transaction
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils.text import slugify
from django.utils.timezone import now
from django_countries import countries


CURRENCIES = [
    'ARS', 'BRL', 'CAD', 'CNY', 'EUR', 'GBP', 'USD', 'UYU',
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
    'travel (transport)',  # 2048
    'utilities',  # 4096
    'work(ish)',  # 8192
    'imported',  # 16384
    'trips',  # 32768
    'investments',  # 65536
]


def month_year_iter(start, end):
    # Adapted from:
    # http://stackoverflow.com/questions/5734438/how-to-create-a-month-iterator
    ym_start = 12 * start.year + start.month - 1
    ym_end = 12 * end.year + end.month
    for ym in range(ym_start, ym_end):
        y, m = divmod(ym, 12)
        yield date(y, m + 1, 1)


class Balance(object):

    def __init__(self, entries, start, end):
        super(Balance, self).__init__()
        assert entries.count() > 0
        assert start <= end, start
        self.start = start
        self.end = end
        self.entries = entries.filter(when__range=(start, end))

    def balance(self):
        totals = self.entries.values('is_income').annotate(
            models.Sum('amount'))
        assert len(totals) <= 2, totals

        result = {
            'start': self.start, 'end': self.end,
            'result': Decimal(0), 'income': Decimal(0), 'expense': Decimal(0),
        }
        for item in totals:
            if item['is_income']:
                result['income'] = item['amount__sum']
            else:
                result['expense'] = item['amount__sum']
        result['result'] = result['income'] - result['expense']
        return result


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
            models.Q(what__icontains=text) | models.Q(notes__icontains=text))

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

    def balance(self, accounts=None, start=None, end=None):
        if accounts:
            entries = self.entry_set.filter(account__in=accounts)
        else:
            entries = self.entry_set.all()

        if not entries:
            return

        if not start:
            start = entries.earliest('when').when
        if not end:
            end = entries.latest('when').when

        # Range test (inclusive).
        assert start <= end
        complete = Balance(entries, start, end).balance()

        months = []
        last_month = None
        sanity_check = Decimal(0)
        for next_month in month_year_iter(start, end):
            if last_month is not None:
                end_of_month = next_month - timedelta(days=1)
                balance = Balance(entries, last_month, end_of_month).balance()
                sanity_check += balance['result']
                months.append(balance)
            last_month = next_month

        balance = Balance(entries, last_month, end).balance()
        sanity_check += balance['result']
        months.append(balance)

        assert sanity_check == complete['result']

        return {'complete': complete, 'months': months}

    @transaction.atomic
    def merge_entries(self, *entries):
        # validate some minimal consistency on entries
        if len(entries) < 2:
            raise ValueError(
                'Need at least 2 entries to merge (got %s).' % len(entries))

        books = {e.book for e in entries}
        if len(books) != 1 or books.pop() != self:
            raise ValueError(
                'Can not merge entries outside this book (got %s).' %
                ', '.join(sorted(b.slug for b in books)))

        accounts = {e.account for e in entries}
        if len(accounts) != 1:
            raise ValueError(
                'Can not merge entries for different accounts (got %s).' %
                ', '.join(sorted(a.slug for a in accounts)))

        countries = {e.country for e in entries}
        if len(countries) != 1:
            raise ValueError(
                'Can not merge entries for different countries (got %s).' %
                ', '.join(sorted(countries)))

        # prepare data for new Entry
        what = ', '.join(sorted(set(e.what for e in entries)))
        amount = sum(e.money for e in entries)
        tags = reduce(operator.or_, [e.tags for e in entries])
        notes = '\n'.join(e.notes for e in entries)
        master = entries[0]
        kwargs = dict(
            book=self, who=master.who, when=master.when, what=what,
            account=accounts.pop(), amount=abs(amount), is_income=amount > 0,
            tags=tags, country=countries.pop(), notes=notes)

        result = Entry.objects.create(**kwargs)
        Entry.objects.filter(id__in=[e.id for e in entries]).delete()

        return result


class AccountManager(models.Manager):

    def by_book(self, book, **kwargs):
        return self.filter(users__book=book, active=True, **kwargs).distinct()


class Account(models.Model):

    name = models.CharField(max_length=256)
    slug = models.SlugField(unique=True)
    users = models.ManyToManyField(User)
    currency_code = models.CharField(
        max_length=3, choices=[(c, c) for c in CURRENCIES])
    parser = models.CharField(max_length=256, blank=True, default='')
    active = models.BooleanField(default=True)

    objects = AccountManager()

    class Meta:
        ordering = ('currency_code', 'name')

    def __str__(self):
        result = '%s %s' % (self.name, self.currency_code)
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

    account = models.ForeignKey(Account)
    regex = models.TextField()
    tag = models.CharField(max_length=256, choices=((t, t) for t in TAGS))
    transfer = models.ForeignKey(
        Account, related_name='transfers', null=True, blank=True)

    class Meta:
        unique_together = ('account', 'regex', 'tag')


class Entry(models.Model):

    book = models.ForeignKey(Book)
    who = models.ForeignKey(User)
    when = models.DateField(default=datetime.today)
    what = models.TextField()
    account = models.ForeignKey(Account)
    amount = models.DecimalField(
        decimal_places=2, max_digits=12,
        validators=[MinValueValidator(Decimal('0'))])
    is_income = models.BooleanField(default=False, verbose_name='Income?')
    tags = BitField(flags=[(t.lower(), t) for t in TAGS])
    country = models.CharField(max_length=2, choices=countries)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = (
            'book', 'account', 'when', 'what', 'amount', 'is_income')
        verbose_name_plural = 'Entries'

    def __str__(self):
        return '%s (%s%s %s, by %s on %s)' % (
            self.what, '+' if self.is_income else '-', self.amount,
            self.account, self.who, self.when)

    @property
    def currency(self):
        return self.account.currency_code

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
    tags_label = models.TextField()
    country_code = models.CharField(max_length=2, choices=countries)
    notes = models.TextField(blank=True)

    creation_date = models.DateTimeField(default=now)
    reason = models.CharField(
        max_length=256, choices=((i, i) for i in (DELETE, MERGE)))

    def __str__(self):
        return '%s: %s (%s%s %s, by %s on %s, %s)' % (
            self.book_slug, self.what,
            '+' if self.is_income else '-', self.amount,
            self.account_slug, self.who_username, self.when, self.tags_label)


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
        tags_label=', '.join(i for i, j in instance.tags.items() if j),
        country_code=instance.country,
        notes=instance.notes,
        reason=EntryHistory.DELETE)
