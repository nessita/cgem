# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
import bitfield.models


class Migration(migrations.Migration):

    dependencies = [
        ('gemcore', '0011_auto_20141009_2009'),
    ]

    operations = [
        migrations.AlterField(
            model_name='account',
            name='currency_code',
            field=models.CharField(choices=[('ARS', 'ARS'), ('BRL', 'BRL'), ('CNY', 'CNY'), ('EUR', 'EUR'), ('GBP', 'GBP'), ('USD', 'USD'), ('UYU', 'UYU')], max_length=3),
        ),
        migrations.AlterField(
            model_name='entry',
            name='tags',
            field=bitfield.models.BitField([('bureaucracy', 'bureaucracy'), ('car', 'car'), ('change', 'change'), ('food', 'food'), ('fun', 'fun'), ('health', 'health'), ('house', 'house'), ('maintainance', 'maintainance'), ('other', 'other'), ('rent', 'rent'), ('taxes', 'taxes'), ('travel (transport)', 'travel (transport)'), ('utilities', 'utilities'), ('work(ish)', 'work(ish)'), ('imported', 'imported'), ('trips', 'trips')], default=None),
        ),
        migrations.AlterUniqueTogether(
            name='entry',
            unique_together=set([('book', 'when', 'what', 'amount')]),
        ),
    ]
