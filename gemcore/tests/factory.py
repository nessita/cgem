# -*- coding: utf-8 -*-

import itertools
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token

from gemcore.models import Account, Book, Entry, ParserConfig

User = get_user_model()


class Factory(object):
    def __init__(self):
        super(Factory, self).__init__()
        self.counter = itertools.count()

    def make_integer(self):
        return next(self.counter)

    def make_slug(self, prefix="slug"):
        return "%s-%s" % (prefix, self.make_integer())

    def make_user(self, username=None, password="test", **kwargs):
        if username is None:
            username = "user-%s" % self.make_integer()
        return User.objects.create_user(
            username=username, password=password, **kwargs
        )

    def make_book(self, slug=None, name=None, users=None, **kwargs):
        i = self.make_integer()
        if name is None:
            name = "Book %s" % i
        if slug is None:
            slug = "book-%s" % i
        book = Book.objects.create(name=name, slug=slug, **kwargs)
        if users:
            for u in users:
                book.users.add(u)

        return book

    def make_account(
        self, name=None, slug=None, currency="USD", users=None, **kwargs
    ):
        i = self.make_integer()
        if name is None:
            name = "Account %s (%s)" % (i, currency)
        if slug is None:
            slug = "account-%s-%s" % (currency, i)
        account = Account.objects.create(
            name=name, slug=slug, currency=currency, **kwargs
        )
        if users:
            for u in users:
                account.users.add(u)

        return account

    def make_tag_regex(self, regex, tag, account=None):
        if account is None:
            account = self.make_account()
        return account.tagregex_set.create(regex=regex, tag=tag)

    def make_entry_data(
        self,
        book=None,
        account=None,
        who=None,
        when=None,
        amount=Decimal("1.0"),
        what=None,
        country="AR",
        **kwargs
    ):
        i = self.make_integer()
        if who is None:
            who = self.make_user()
        if book is None:
            book = self.make_book(users=[who])
        if account is None:
            account = self.make_account(users=[who])
        if what is None:
            what = "Description of entry %i" % i
        if when is None:
            when = date.today()
        tags = kwargs.pop("tags", [settings.ENTRY_DEFAULT_TAG])

        result = dict(
            book=book,
            account=account,
            who=who,
            what=what,
            when=when,
            amount=amount,
            tags=tags,
            country=country,
            **kwargs
        )
        return result

    def make_entry(self, save=True, **kwargs):
        data = self.make_entry_data(**kwargs)
        result = Entry(**data)
        if save:
            result.save()
        return result

    def make_parser_config(self, name=None, **kwargs):
        i = self.make_integer()
        if name is None:
            name = "Parser %s" % i
        return ParserConfig.objects.create(name=name, **kwargs)

    def make_token(self, user=None):
        if user is None:
            user = self.make_user()
        return Token.objects.create(user=user)
