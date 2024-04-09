# Generated by Django 5.0.3 on 2024-04-09 01:05

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

from gemcore.constants import ChoicesMixin


class Migration(migrations.Migration):

    dependencies = [
        (
            'gemcore',
            '0005_parserconfig_delimiter_alter_entry_country_and_more',
        ),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Asset',
            fields=[
                (
                    'id',
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                ('name', models.CharField(max_length=4096)),
                ('slug', models.SlugField(unique=True)),
                ('since', models.DateField()),
                ('until', models.DateField(blank=True, null=True)),
                ('notes', models.TextField(blank=True)),
                (
                    'category',
                    models.CharField(
                        blank=True,
                        choices=ChoicesMixin.ASSET_CHOICES,
                        default='',
                        max_length=256,
                    ),
                ),
                ('users', models.ManyToManyField(to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddField(
            model_name='entry',
            name='asset',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='gemcore.asset',
            ),
        ),
    ]
