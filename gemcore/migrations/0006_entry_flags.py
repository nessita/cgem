# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
import bitfield.models


class Migration(migrations.Migration):

    dependencies = [
        ('gemcore', '0005_auto_20140927_2326'),
    ]

    operations = [
        migrations.AddField(
            model_name='entry',
            name='flags',
            field=bitfield.models.BitField([('ar', 'AR'), ('uy', 'UY'), ('bureaucracy', 'bureaucracy'), ('car', 'car'), ('change', 'change'), ('food', 'food'), ('fun', 'fun'), ('health', 'health'), ('house', 'house'), ('maintainance', 'maintainance'), ('other', 'other'), ('rent', 'rent'), ('taxes', 'taxes'), ('travel', 'travel'), ('utilities', 'utilities'), ('withdraw', 'withdraw')], null=True, default=None),
            preserve_default=True,
        ),
    ]
