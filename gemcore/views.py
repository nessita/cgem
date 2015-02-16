import operator

from collections import OrderedDict
from datetime import date, datetime
from functools import reduce
from io import StringIO, TextIOWrapper
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.core.urlresolvers import reverse
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_http_methods

from gemcore.forms import (
    AccountTransferForm,
    BalanceForm,
    BookForm,
    CSVExpenseForm,
    EntryForm,
)
from gemcore.models import Account, Book, Entry
from gemcore.parse import BankCSVParser, ExpenseCSVParser, TripCSVParser


ENTRIES_PER_PAGE = 25
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

    when = request.GET.get('when')
    if when:
        entries = book.entry_set.filter(when=when)

    try:
        year = int(request.GET.get('year'))
    except (ValueError, TypeError):
        year = None
    else:
        entries = entries.filter(when__year=year)

    month = request.GET.get('month')
    try:
        entries = entries.filter(when__month=MONTHS[month])
    except (KeyError, ValueError, TypeError):
        month = None

    who = request.GET.get('who')
    if who:
        entries = entries.filter(who__username=who)

    country = request.GET.get('country')
    if country:
        entries = entries.filter(country=country)

    account = request.GET.get('account')
    if account:
        entries = entries.filter(account__slug=account)

    used_tags = set(request.GET.getlist('tag', []))
    if used_tags:
        tags = reduce(
            operator.or_,
            [getattr(Entry.tags, t.lower(), 0) for t in used_tags])
        entries = entries.filter(tags=tags)

    entries = entries.order_by('-when', 'who')

    years = [] if year else book.years(entries)
    months = [] if month else [
        d.strftime('%b') for d in sorted(
            {date(2000, d.month, 1)
             for d in entries.values_list('when', flat=True)}
        )
    ]
    countries = [] if country else book.countries(entries)
    accounts = [] if account else book.accounts(entries)
    users = [] if who else book.who(entries)
    tags = book.tags(entries)

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
        country=country, account=account, years=years, months=months,
        users=users, countries=countries, accounts=accounts, tags=tags,
        q=q, when=when, used_tags=used_tags,
        page_range=page_range, start=start, end=end,
        balance_form=BalanceForm(book),
    )
    return render(request, 'gemcore/entries.html', context)


@require_http_methods(['GET', 'POST'])
@login_required
def entry(request, book_slug, entry_id=None):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)
    entry = None
    if entry_id:
        entry = get_object_or_404(Entry, book=book, id=entry_id)

    context = dict(book=book, entry=entry)
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

        initial = dict(who=who, currency=currency)
        when = request.GET.get('when')
        if when:
            initial['when'] = when

        form = EntryForm(instance=entry, initial=initial)
        if entry:
            try:
                context['entry_prev'] = entry.get_previous_by_when()
            except Entry.DoesNotExist:
                pass
            try:
                context['entry_next'] = entry.get_next_by_when()
            except Entry.DoesNotExist:
                pass

    context['form'] = form
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
            csv_file = form.cleaned_data.get('csv_file')
            if csv_file:
                # Hack around: "iterator should return strings, not bytes
                # (did you open the file in text mode?)"
                csv_file.readable = lambda: True
                csv_file.writable = lambda: False
                csv_file.seekable = lambda: True
                csv_file = TextIOWrapper(csv_file, encoding='utf-8')
                # end hack
            else:
                csv_content = form.cleaned_data.get('csv_content')
                csv_file = StringIO(csv_content)
                csv_file.name = 'test.csv'

            source = form.cleaned_data['source']
            if source == 'bank':
                result = BankCSVParser(book).parse(csv_file)
            elif source == 'trips':
                result = TripCSVParser(book).parse(csv_file)
            else:
                assert source == 'expense'
                result = ExpenseCSVParser(book).parse(csv_file)

            success = len([e for e in result['entries'] if e])
            error = sum(len(i) for i in result['errors'].values())
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


@require_http_methods(['GET', 'POST'])
@login_required
def account_transfer(request, book_slug):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)

    if request.method == 'POST':
        form = AccountTransferForm(request.user, book, request.POST)
        if form.is_valid():
            source_account = form.cleaned_data.get('source_account')
            source_amount = form.cleaned_data.get('source_amount')
            target_account = form.cleaned_data.get('target_account')
            target_amount = form.cleaned_data.get('target_amount')
            when = form.cleaned_data.get('when')
            what = form.cleaned_data.get('what')
            country = form.cleaned_data.get('country')
            tags = Entry.tags.change

            Entry.objects.create(
                book=book, who=request.user, when=when,
                what=what + ' (source)',
                account=source_account, amount=source_amount,
                is_income=False, country=country, tags=tags,
            )
            Entry.objects.create(
                book=book, who=request.user, when=when,
                what=what + ' (target)',
                account=target_account, amount=target_amount,
                is_income=True, country=country, tags=tags,
            )

            return HttpResponseRedirect(
                reverse('entries', kwargs=dict(book_slug=book_slug)))
    else:
        form = AccountTransferForm(request.user, book)

    context = dict(form=form)
    return render(request, 'gemcore/transfer.html', context)


@require_http_methods(['GET', 'POST'])
@login_required
def balance(request, book_slug, account_slug=None, start=None, end=None):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)

    if request.method == 'POST':
        form = BalanceForm(book, data=request.POST)
        if form.is_valid():
            account = form.cleaned_data['account']
            url = reverse(
                'balance',
                kwargs=dict(book_slug=book.slug, account_slug=account.slug))
            start = form.cleaned_data['start']
            end = form.cleaned_data['end']
            qs = {}
            if start:
                qs['start'] = start
            if end:
                qs['end'] = end
            if qs:
                url += '?' + urlencode(qs)
            return HttpResponseRedirect(url)

    account = None
    balance = None
    if account_slug:
        account = get_object_or_404(Account, slug=account_slug)
        if book.id not in account.users.all().values_list('book', flat=True):
            raise Http404
        start = request.GET.get('start')
        end = request.GET.get('end')
        if start:
            start = datetime.strptime(start, '%Y-%m-%d').date()
        if end:
            end = datetime.strptime(end, '%Y-%m-%d').date()
        balance = account.balance(book, start, end)

    form = BalanceForm(
        book=book, initial=dict(account=account, start=start, end=end))
    context = {
        'account': account,
        'balance': balance,
        'book': book,
        'form': form,
    }
    return render(request, 'gemcore/balance.html', context)
