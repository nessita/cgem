CGEM
====

[![Build Status](https://travis-ci.org/nessita/cgem.svg?branch=master)](https://travis-ci.org/nessita/cgem)

CGEM could stand for "Custom Great Expense Manager" or, in spanish, "Cuánto
Gastamos Este Mes?". CGEM is a simple accounting and reporting web service.

It supports handling multiple accounting books, for example to track the family
accounting, the company accounting, etc.

You can define a very naive access map by defining which users can access which
book.

Setup
-----

CGEM is a pure Python3 + Django service, so all you need is a Python3 virtualenv
with all the dependencies from requirement.txt installed, and just run the
server either with the Django test server, or with the provided wsgi file.
