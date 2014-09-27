# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


def copy_currency(apps, schema_editor):
    Account = apps.get_model("gemcore", "Account")
    for account in Account.objects.all():
        account.currency_code = account.currency.code
        account.save()


class Migration(migrations.Migration):

    dependencies = [
        ('gemcore', '0003_auto_20140903_2351'),
    ]

    operations = [
        migrations.AddField(
            model_name='account',
            name='currency_code',
            field=models.CharField(choices=[('ARS', 'ARS'), ('EUR', 'EUR'), ('USD', 'USD'), ('UYU', 'UYU'), ('GBP', 'GBP')], max_length=3, null=True),
            preserve_default=True,
        ),
        migrations.RunPython(copy_currency),
    ]
