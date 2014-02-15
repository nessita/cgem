from decimal import Decimal

from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from taggit.managers import TaggableManager


CURRENCIES = [
    'ARS', 'EUR', 'USD', 'UYU', 'GBP',
]

TAGS = [
    'super', 'auto', 'servicios', 'impuestos',
]


class Book(models.Model):

    name = models.CharField(max_length=256)
    users = models.ManyToManyField(User)


class Currency(models.Model):

    code = models.CharField(max_length=3, choices=[(c, c) for c in CURRENCIES])


class Expense(models.Model):

    book = models.ForeignKey(Book)
    who = models.ForeignKey(User)  #, limit_choices_to={'who__in': 'book__users'})
    when = models.DateTimeField()
    what = models.TextField()
    amount = models.DecimalField(
        decimal_places=2, max_digits=12,
        validators=[MinValueValidator(Decimal('0.01'))])
    currency = models.ForeignKey(Currency, default='ARS')

    tags = TaggableManager()
