# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('gemcore', '0004_account_currency_code'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='account',
            options={'ordering': ('currency_code', 'name')},
        ),
        migrations.RemoveField(
            model_name='account',
            name='currency',
        ),
        migrations.DeleteModel(
            name='Currency',
        ),
        migrations.AlterField(
            model_name='account',
            name='currency_code',
            field=models.CharField(choices=[('ARS', 'ARS'), ('EUR', 'EUR'), ('USD', 'USD'), ('UYU', 'UYU'), ('GBP', 'GBP')], max_length=3),
        ),
    ]
