import operator

from collections import OrderedDict
from datetime import date
from functools import reduce
from io import TextIOWrapper

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_http_methods
from taggit.models import Tag

from gemcore.forms import BookForm, CSVExpenseForm, EntryForm
from gemcore.models import Book, Entry
from gemcore.parse import ExpenseCSVParser


ENTRIES_PER_PAGE = 15
MAX_PAGES = 4
MONTHS = OrderedDict(
    [(date(2000, i, 1).strftime('%b'), i) for i in range(1, 13)])


def remove_thing(request, thing):
    if request.method == 'POST':
        if 'yes' in request.POST:
            thing.delete()
        return HttpResponseRedirect(reverse(home))

    return render(request, 'gemcore/remove.html', dict(thing=thing))


@require_GET
@login_required
def home(request):
    return HttpResponseRedirect(reverse(books))


@require_GET
@login_required
def books(request):
    books = request.user.book_set.all()
    context = dict(books=books)
    return render(request, 'gemcore/books.html', context)


@require_http_methods(['GET', 'POST'])
@login_required
def book(request, book_slug=None):
    book = None
    if book_slug:
        book = get_object_or_404(Book, slug=book_slug, users=request.user)

    if request.method == 'POST':
        form = BookForm(instance=book, data=request.POST)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(reverse(home))
    else:
        form = BookForm(instance=book)
    return render(request, 'gemcore/book.html', dict(form=form, book=book))


@require_http_methods(['GET', 'POST'])
@login_required
def book_remove(request, book_slug):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)
    return remove_thing(request, book)


@require_GET
@login_required
def entries(request, book_slug):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)

    q = request.GET.get('q')
    if q:
        entries = book.entry_set.filter(what__icontains=q)
    else:
        entries = book.entry_set.all()

    try:
        year = int(request.GET.get('year'))
    except (ValueError, TypeError):
        year = None
        all_years = book.years(entries)
    else:
        entries = entries.filter(when__year=year)

    month = request.GET.get('month')
    try:
        entries = entries.filter(when__month=MONTHS[month])
    except (KeyError, ValueError, TypeError):
        month = None
        months = entries.values_list('when', flat=True)
        all_months = [
            d.strftime('%b')
            for d in sorted({date(2000, d.month, 1) for d in months})
        ]

    who = request.GET.get('who')
    if who:
        entries = entries.filter(who__username=who)
    else:
        all_users = book.who(entries)

    country = request.GET.get('country')
    if country:
        entries = entries.filter(country=country)
    else:
        all_countries = book.countries(entries)

    tags = set(request.GET.getlist('tag', []))
    if tags:
        flags = reduce(
            operator.or_, [getattr(Entry.flags, t.lower(), 0) for t in tags])
        entries = entries.filter(flags=flags)

    entries = entries.order_by('-when', 'who')

    all_tags = book.tags(entries)
    available_tags = set(str(i) for i in all_tags.keys()).difference(tags)

    paginator = Paginator(entries, ENTRIES_PER_PAGE)
    page = request.GET.get('page')
    try:
        entries = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        page = 1
        entries = paginator.page(page)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        page = paginator.num_pages
        entries = paginator.page(paginator.num_pages)
    else:
        page = int(page)

    if paginator.num_pages <= MAX_PAGES:
        start = 1
        end = paginator.num_pages
    else:
        half = MAX_PAGES // 2
        start = page - half
        end = page + half
        if start < 1 and end - start < paginator.num_pages:
            end = end - start + 1
            start = 1
        if end > paginator.num_pages and start > 1:
            start = start - (end - paginator.num_pages)
            end = paginator.num_pages

    page_range = range(start, end + 1)
    context = dict(
        entries=entries, book=book, year=year, month=month, who=who,
        where=country,
        all_years=all_years, all_months=all_months, all_users=all_users,
        all_countries=all_countries, all_tags=all_tags,
        q=q, page_range=page_range, start=start, end=end,
        available_tags=available_tags, used_tags=tags)

    return render(request, 'gemcore/entries.html', context)


@require_http_methods(['GET', 'POST'])
@login_required
def entry(request, book_slug, entry_id=None):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)
    entry = None
    if entry_id:
        entry = get_object_or_404(Entry, book=book, id=entry_id)

    if request.method == 'POST':
        form = EntryForm(instance=entry, data=request.POST)
        if form.is_valid():
            redirect_url = 'add-entry' if entry is None else 'entries'
            entry = form.save(book=book)
            messages.success(
                request, 'Entry "%s" successfully processed.' % entry)
            return HttpResponseRedirect(
                reverse(redirect_url, kwargs=dict(book_slug=book_slug)))
    else:
        currency = None
        who = request.user
        if entry is None:
            try:
                last_entry = Entry.objects.filter(
                    who=request.user, book=book).latest('when')
                currency = last_entry.currency
            except Entry.DoesNotExist:
                pass
        else:
            who = entry.who
        form = EntryForm(
            instance=entry, initial=dict(who=who, currency=currency))

    all_tags = Tag.objects.all()
    context = dict(
        form=form, book=book, entry=entry, all_tags=all_tags)
    return render(request, 'gemcore/entry.html', context)


@require_http_methods(['GET', 'POST'])
@login_required
def entry_remove(request, book_slug, entry_id):
    entry = get_object_or_404(
        Entry, book__slug=book_slug, book__users=request.user, id=entry_id)
    return remove_thing(request, entry)


@require_http_methods(['GET', 'POST'])
@login_required
def load_from_file(request, book_slug):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)

    if request.method == 'POST':
        form = CSVExpenseForm(request.POST, request.FILES)
        if form.is_valid():
            csv_file = form.cleaned_data['csv_file']

            # Hack around: "iterator should return strings, not bytes
            # (did you open the file in text mode?)"
            csv_file.readable = lambda: True
            csv_file.writable = lambda: False
            csv_file.seekable = lambda: True
            csv_file = TextIOWrapper(csv_file, encoding='utf-8')
            # end hack

            result = ExpenseCSVParser(book).parse(csv_file)
            success = len(result['entries'])
            error = len(result['errors'])
            if not error:
                messages.success(
                    request, 'File %s successfully parsed (%s entries added).'
                    % (success, csv_file.name))
            elif success:
                messages.warning(
                    request,
                    'File %s partially parsed (%s successes, %s errors).' %
                    (csv_file.name, success, error))
            else:
                messages.error(
                    request, 'File %s could not be parsed (%s errors).' %
                    (csv_file.name, error))

            if error:
                for e, errors in result['errors'].items():
                    error_msg = ', '.join(str(i) for i in errors)
                    messages.error(request, '%s: %s' % (e, error_msg))

            return HttpResponseRedirect(
                reverse('entries', kwargs=dict(book_slug=book_slug)))
    else:
        form = CSVExpenseForm()

    context = dict(form=form)
    return render(request, 'gemcore/load.html', context)
