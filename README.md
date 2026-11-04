CGEM
====

![tests](https://github.com/nessita/cgem/actions/workflows/django.yml/badge.svg)
[![codecov](https://codecov.io/gh/nessita/cgem/branch/master/graph/badge.svg?token=AUOMSQ4PSF)](https://codecov.io/gh/nessita/cgem)


CGEM could stand for "Custom Great Expense Manager" or, in spanish, "Cuánto
Gastamos Este Mes?". CGEM is a simple accounting and reporting web service
built in Django.

It supports handling multiple accounting books, for example to track the family
accounting, the company accounting, etc.

You can define a very naive ACL by defining which users can access which
book.

Usage
------

CGEM is a pure Python3 + Django service, so all you need is a Python3
virtualenv with all the dependencies from requirement.txt installed, and just
run the server either with the Django test server, or with the provided wsgi
file.

Dates and timezones
------------------

Financial dates are calendar dates and retain the date entered or imported,
without timezone conversion. Automatic date defaults and asset expiration use
the UTC calendar day. An asset is inactive on its `until` date. Audit
timestamps are timezone-aware and use UTC.

Contributing
------------

Tests
_____


As with any Django project, tests can be run with:

```
python3 manage.py test
```

