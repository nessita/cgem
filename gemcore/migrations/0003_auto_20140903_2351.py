# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('gemcore', '0002_auto_20140830_2348'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='entry',
            options={'verbose_name_plural': 'Entries'},
        ),
        migrations.AlterUniqueTogether(
            name='entry',
            unique_together=set([('book', 'who', 'when', 'what', 'amount')]),
        ),
    ]
