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

Tailwind CSS (standalone CLI)
----------------------------

The Tailwind build uses a standalone executable, without Node. The executable
and generated stylesheet are git-ignored, so each machine needs its own binary
and build.

From the project root, download the Linux x64 binary:

```bash
curl --fail --location --silent --show-error \
  "https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-x64" \
  --output tailwindcss
chmod +x tailwindcss
```

For another OS or architecture, use the matching asset from the releases page:
https://github.com/tailwindlabs/tailwindcss/releases.

Build the stylesheet explicitly:

```bash
./tailwindcss -o gemcore/static/css/styles.css --minify
```

The standalone CLI uses its default Tailwind import and automatically scans
the project for class names, including templates, Python form definitions, and
JavaScript. Complete utility class names must appear in the sources;
interpolated class fragments are not detected. Register new source locations
in `gemcore/assets.py` if their edits should trigger development rebuilds.

In development, with `DEBUG = True`, `python manage.py runserver` builds the
stylesheet when the autoreloader starts. Template and registered JavaScript
edits rebuild it without restarting the server. Python edits retain
the normal restart behavior, and the restarted server builds the stylesheet.
Build failures are reported in the terminal. Refresh the browser to see edits.

With `runserver --noreload`, use the explicit build command or a separate watch
process:

```bash
./tailwindcss -o gemcore/static/css/styles.css --watch
```

The hook does not execute builds under Gunicorn, tests, or other management
commands. In production, build after updating the checkout and before collecting
static files:

```bash
./tailwindcss -o gemcore/static/css/styles.css --minify
python manage.py collectstatic --noinput
```

The shared base template loads the generated Tailwind stylesheet. The
application UI uses Tailwind throughout. CI does not build the stylesheet, so
run the build explicitly before `collectstatic` in deployment.

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

