# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
from decimal import Decimal
import autoslug.fields
import datetime
import django.core.validators
from django.conf import settings
import taggit.managers


class Migration(migrations.Migration):

    dependencies = [
        ('taggit', '__first__'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Book',
            fields=[
                ('id', models.AutoField(serialize=False, verbose_name='ID', auto_created=True, primary_key=True)),
                ('name', models.CharField(max_length=256)),
                ('slug', autoslug.fields.AutoSlugField(editable=False, unique=True)),
                ('users', models.ManyToManyField(to=settings.AUTH_USER_MODEL)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='Currency',
            fields=[
                ('id', models.AutoField(serialize=False, verbose_name='ID', auto_created=True, primary_key=True)),
                ('code', models.CharField(choices=[('ARS', 'ARS'), ('EUR', 'EUR'), ('USD', 'USD'), ('UYU', 'UYU'), ('GBP', 'GBP')], max_length=3)),
            ],
            options={
                'verbose_name_plural': 'Currencies',
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='Expense',
            fields=[
                ('id', models.AutoField(serialize=False, verbose_name='ID', auto_created=True, primary_key=True)),
                ('when', models.DateField(default=datetime.datetime.today)),
                ('what', models.TextField()),
                ('amount', models.DecimalField(max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal('0.01'))], decimal_places=2)),
                ('book', models.ForeignKey(to='gemcore.Book')),
                ('currency', models.ForeignKey(to='gemcore.Currency')),
                ('tags', taggit.managers.TaggableManager(help_text='A comma-separated list of tags.', through='taggit.TaggedItem', verbose_name='Tags', to='taggit.Tag')),
                ('who', models.ForeignKey(to=settings.AUTH_USER_MODEL)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
    ]
