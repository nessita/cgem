# -*- coding: utf-8 -*-

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.text import slugify
from taggit.managers import TaggableManager
from taggit.models import Tag


CURRENCIES = [
    'ARS', 'EUR', 'USD', 'UYU', 'GBP',
]

RAW_TAG_SQL = """
    SELECT taggit_tag.id, taggit_tag.name, COUNT(taggit_tag.id) as tag_count
    FROM taggit_tag
    JOIN taggit_taggeditem ON taggit_tag.id = taggit_taggeditem.tag_id
    JOIN gemcore_entry ON taggit_taggeditem.object_id = gemcore_entry.id
    WHERE gemcore_entry.book_id = %s AND gemcore_entry.id IN (%s)
    GROUP BY taggit_tag.id;
"""


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
        result = defaultdict(int)

        qs = Tag.objects.raw(
            RAW_TAG_SQL % (self.id, ', '.join(str(e.id) for e in entries)))
        result = {q.name: q.tag_count for q in qs}
        return result

    def years(self, entries=None):
        if entries is None:
            entries = self.entry_set.all()

        result = {}
        if entries.count() == 0:
            return result

        oldest = entries.order_by('when')[0].when.year
        newest = entries.order_by('-when')[0].when.year
        for year in range(oldest, newest + 1):
            year_count = entries.filter(when__year=year).count()
            if year_count:
                result[year] = year_count
        return result

    def who(self, entries=None):
        if entries is None:
            entries = self.entry_set.all()
        result = defaultdict(int)
        for d in entries.values_list('who__username', flat=True):
            result[d] += 1
        return dict(result)


class Currency(models.Model):

    code = models.CharField(max_length=3, choices=[(c, c) for c in CURRENCIES])

    class Meta:
        verbose_name_plural = "Currencies"

    def __str__(self):
        return self.code


class Account(models.Model):

    name = models.CharField(max_length=256)
    slug = models.SlugField(unique=True)
    users = models.ManyToManyField(User)
    currency = models.ForeignKey(Currency)

    class Meta:
        ordering = ('currency', 'name')

    def __str__(self):
        if self.users.count() == 1:
            result = '%s %s %s' % (
                self.currency, self.users.get().username, self.name)
        else:
            result = '%s shared %s' % (self.currency, self.name)
        return result

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        return super(Account, self).save(*args, **kwargs)


class Entry(models.Model):

    book = models.ForeignKey(Book)
    who = models.ForeignKey(User)
    when = models.DateField(default=datetime.today)
    what = models.TextField()
    account = models.ForeignKey(Account)
    amount = models.DecimalField(
        decimal_places=2, max_digits=12,
        validators=[MinValueValidator(Decimal('0.01'))])
    is_income = models.BooleanField(default=False)

    tags = TaggableManager()

    class Meta:
        unique_together = ('book', 'who', 'when', 'what', 'amount')
        verbose_name_plural = 'Entries'

    def __str__(self):
        return '%s (%s %s, by %s on %s)' % (
            self.what, self.amount, self.account, self.who, self.when)

    @property
    def currency(self):
        return self.account.currency
