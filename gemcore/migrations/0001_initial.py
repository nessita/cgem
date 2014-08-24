# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
from django.conf import settings
import autoslug.fields
import taggit.managers
from decimal import Decimal
import datetime
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('taggit', '__first__'),
    ]

    operations = [
        migrations.CreateModel(
            name='Book',
            fields=[
                ('id', models.AutoField(primary_key=True, verbose_name='ID', serialize=False, auto_created=True)),
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
                ('id', models.AutoField(primary_key=True, verbose_name='ID', serialize=False, auto_created=True)),
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
                ('id', models.AutoField(primary_key=True, verbose_name='ID', serialize=False, auto_created=True)),
                ('when', models.DateField(default=datetime.datetime.today)),
                ('what', models.TextField()),
                ('amount', models.DecimalField(decimal_places=2, validators=[django.core.validators.MinValueValidator(Decimal('0.01'))], max_digits=12)),
                ('book', models.ForeignKey(to='gemcore.Book')),
                ('currency', models.ForeignKey(to='gemcore.Currency', default='ARS')),
                ('tags', taggit.managers.TaggableManager(to='taggit.Tag', verbose_name='Tags', through='taggit.TaggedItem', help_text='A comma-separated list of tags.')),
                ('who', models.ForeignKey(to=settings.AUTH_USER_MODEL)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
    ]
