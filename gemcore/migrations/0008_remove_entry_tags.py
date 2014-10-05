# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('gemcore', '0007_auto_20140928_2102'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='entry',
            name='tags',
        ),
    ]
