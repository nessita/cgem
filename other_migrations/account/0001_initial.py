# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
import django.utils.timezone
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='EmailAddress',
            fields=[
                ('id', models.AutoField(serialize=False, verbose_name='ID', primary_key=True, auto_created=True)),
                ('email', models.EmailField(unique=True, max_length=254, verbose_name='e-mail address')),
                ('verified', models.BooleanField(verbose_name='verified', default=False)),
                ('primary', models.BooleanField(verbose_name='primary', default=False)),
                ('user', models.ForeignKey(verbose_name='user', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name_plural': 'email addresses',
                'verbose_name': 'email address',
            },
        ),
        migrations.CreateModel(
            name='EmailConfirmation',
            fields=[
                ('id', models.AutoField(serialize=False, verbose_name='ID', primary_key=True, auto_created=True)),
                ('created', models.DateTimeField(verbose_name='created', default=django.utils.timezone.now)),
                ('sent', models.DateTimeField(null=True, verbose_name='sent')),
                ('key', models.CharField(unique=True, max_length=64, verbose_name='key')),
                ('email_address', models.ForeignKey(verbose_name='e-mail address', to='account.EmailAddress')),
            ],
            options={
                'verbose_name_plural': 'email confirmations',
                'verbose_name': 'email confirmation',
            },
        ),
    ]
