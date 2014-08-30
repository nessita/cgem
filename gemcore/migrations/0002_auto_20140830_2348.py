# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
import taggit.managers
import django.core.validators
from django.conf import settings
import datetime
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        ('taggit', '__first__'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('gemcore', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Entry',
            fields=[
                ('id', models.AutoField(verbose_name='ID', auto_created=True, primary_key=True, serialize=False)),
                ('when', models.DateField(default=datetime.datetime.today)),
                ('what', models.TextField()),
                ('amount', models.DecimalField(validators=[django.core.validators.MinValueValidator(Decimal('0.01'))], decimal_places=2, max_digits=12)),
                ('is_income', models.BooleanField(default=False)),
                ('account', models.ForeignKey(to='gemcore.Account')),
                ('book', models.ForeignKey(to='gemcore.Book')),
                ('tags', taggit.managers.TaggableManager(verbose_name='Tags', help_text='A comma-separated list of tags.', to='taggit.Tag', through='taggit.TaggedItem')),
                ('who', models.ForeignKey(to=settings.AUTH_USER_MODEL)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.RemoveField(
            model_name='expense',
            name='account',
        ),
        migrations.RemoveField(
            model_name='expense',
            name='book',
        ),
        migrations.RemoveField(
            model_name='expense',
            name='tags',
        ),
        migrations.RemoveField(
            model_name='expense',
            name='who',
        ),
        migrations.DeleteModel(
            name='Expense',
        ),
        migrations.AlterModelOptions(
            name='account',
            options={'ordering': ('currency', 'name')},
        ),
    ]
