# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('gemcore', '0009_auto_20141005_1831'),
    ]

    operations = [
        migrations.AddField(
            model_name='entry',
            name='notes',
            field=models.TextField(default='', blank=True),
            preserve_default=False,
        ),
    ]
