from decimal import Decimal

from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models


class Category(models.Model):

    name = models.CharField(max_length=256)


class Expense(models.Model):

    category = models.ForeignKey(Category)
    who = models.ForeignKey(User)
    when = models.DateTimeField()
    what = models.TextField()
    amount = models.DecimalField(
        decimal_places=2, max_digits=12,
        validators=[MinValueValidator(Decimal('0.01'))])
