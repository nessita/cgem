# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('gemcore', '0008_remove_entry_tags'),
    ]

    operations = [
        migrations.RenameField(
            model_name='entry',
            old_name='flags',
            new_name='tags',
        ),
    ]
