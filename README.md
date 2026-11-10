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

Entry categories (tags)
-----------------------

Each entry has exactly one category, such as Food, Salary, or Investments.
These categories are called "tags" in the UI, API, and settings; they are not
multiple free-form labels.

Configure them in `gem/local_settings.py` using `ENTRY_TAGS`:

```python
ENTRY_TAGS = {
    "choices": [
        ("IMPD", "Imported"),
        ("CHNG", "Change"),
        ("FD", "Food"),
        ("WORK", "Salary"),
        ("RENT", "Rental"),
        ("INVS", "Investments"),
        # Include the rest of your categories here.
    ],
    "default": "IMPD",
    "transfer": "CHNG",
}
```

`choices` lists category codes and their display labels. `default` is the
fallback for imported or API-created entries when account rules do not assign
a category. `transfer` identifies currency-change movements. Both must reference
codes in `choices`, and they must differ.

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

Entries API
-----------

`/api/entries/` and `/api/<book_slug>/entries/` accept token-authenticated GET
and POST requests:

```http
Authorization: Token <token>
```

`/api/entries/` uses an accessible book with `default=True`, or the user's
only book if none is marked as default. No accessible books returns 404.
Multiple accessible defaults, or multiple books without a default, return 400.
For compatibility with legacy callers, `book` values in the query string and
request body are ignored.

Use `/api/<book_slug>/entries/` to select a book explicitly. Missing or
inaccessible books return 404. The URL selects the book for every entry;
conflicting per-entry `book` values are rejected. A query-string `book` value
does not override the URL.

GET returns `count`, `next`, `previous`, and `results`, ordered by descending
date, description, and entry ID. The default page size is 25; `page_size` accepts
1 through 100 and `page` selects a page. An out-of-range page returns 404.

Supported filters combine with AND:

| Parameter | Value |
| --- | --- |
| `account` | Account slug, including historical inactive accounts |
| `start`, `end` | Inclusive calendar dates in `YYYY-MM-DD` format |
| `country` | Country code, or an empty value for no country |
| `currency` | Currency code |
| `who` | Username |
| `tag` | Tag code or name; repeat to require all supplied tags |
| `is_income` | `true` for income, `false` for expenses |

For example:

```text
/api/family/entries/?start=2026-11-01&end=2026-11-30&is_income=false
```

Invalid filters, unknown parameters, reversed date ranges, and repeated filter
or pagination parameters other than `tag` return 400. The `book` parameter is
ignored, and DRF handles its format parameter (for example, `format=json`).
Text search is not supported.

POST accepts either a single entry object or an array of entries. Each entry
requires `account` (slug), `what`, `amount` (a decimal string), and `country`.
Optional fields are `when`, `is_income`, `tags`, and `notes`. Omitted dates use
the UTC calendar day, omitted `is_income` defaults to false, and omitted tags
use account rules or the configured default tag. Each entry must have exactly
one tag; explicit empty lists, multiple tags, and account rules that resolve to
multiple tags are rejected. The authenticated user is always recorded as `who`.
Accounts must be active and available to the book.

```http
POST /api/family/entries/
Content-Type: application/json
Authorization: Token <token>

[
  {"account": "cash", "what": "Lunch", "amount": "12.50", "country": "US"},
  {"account": "cash", "what": "Bus", "amount": "2.00", "country": "US"}
]
```

Single-entry success returns the created entry with status 201. Bulk requests
follow file-import behavior: valid rows are saved and invalid or duplicate rows
are reported without stopping the remaining rows. The response contains
`entries` and `errors`; each error has a zero-based `index` and validation
`errors`. The status is 201 when all rows succeed, 200 for partial success, and
400 when all rows fail or the array is empty. Check bulk errors before retrying;
already-created entries will be reported as duplicates.

The `scripts/add-expense.py` client selects an explicit book with `--book`.
Omitting it uses the default or sole accessible book.

Contributing
------------

Tests
_____


As with any Django project, tests can be run with:

```
python3 manage.py test
```

