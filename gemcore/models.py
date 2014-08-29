# -*- coding: utf-8 -*-

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.text import slugify
from taggit.managers import TaggableManager


CURRENCIES = [
    'ARS', 'EUR', 'USD', 'UYU', 'GBP',
]

TAGS = [
    'super', 'auto', 'servicios', 'impuestos',
]


class Book(models.Model):

    name = models.CharField(max_length=256)
    slug = models.SlugField(unique=True)
    users = models.ManyToManyField(User)

    def __str__(self):
        return self.name

    def clean(self):
        if not self.slug:
            self.slug = slugify(self.name)
        return super(Book, self).clean()

    def latest_expenses(self):
        return self.expense_set.all().order_by('-when')[:5]

    def tags(self, expenses=None):
        if expenses is None:
            expenses = self.expense_set.all()
        result = defaultdict(int)
        for e in expenses.filter(tags__isnull=False).distinct():
            for t in e.tags.all():
                result[t] += 1

        # templates can not handle defaultdicts
        return dict(result)

    def years(self, expenses=None):
        if expenses is None:
            expenses = self.expense_set.all()

        result = {}
        if expenses.count() == 0:
            return result

        oldest = expenses.order_by('when')[0].when.year
        newest = expenses.order_by('-when')[0].when.year
        for year in range(oldest, newest + 1):
            year_count = expenses.filter(when__year=year).count()
            if year_count:
                result[year] = year_count
        return result

    def who(self, expenses=None):
        if expenses is None:
            expenses = self.expense_set.all()
        result = {}
        for d in expenses.values('who__username').annotate(
                models.Count('who')):
            result[d['who__username']] = d['who__count']
        return result


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

    def __str__(self):
        if self.users.count() == 1:
            result = '%s %s %s' % (
                self.name, self.currency, self.users.get().username)
        else:
            result = '%s %s shared' % (self.name, self.currency)
        return result

    def clean(self):
        if not self.slug:
            self.slug = slugify(self.name)
        return super(Account, self).clean()


class Expense(models.Model):

    book = models.ForeignKey(Book)
    who = models.ForeignKey(User)
    when = models.DateField(default=datetime.today)
    what = models.TextField()
    account = models.ForeignKey(Account)
    amount = models.DecimalField(
        decimal_places=2, max_digits=12,
        validators=[MinValueValidator(Decimal('0.01'))])

    tags = TaggableManager()

    def __str__(self):
        return '%s (%s %s, by %s on %s)' % (
            self.what, self.currency, self.amount, self.who, self.when)

    @property
    def currency(self):
        return self.account.currency
