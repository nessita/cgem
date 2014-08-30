from django.contrib.auth.decorators import login_required
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_http_methods

from gemcore.forms import BookForm, EntryForm
from gemcore.models import Book, Entry


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
    return render(request, 'gemcore/books.html', dict(books=books))


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
    entries = book.entry_set.all()

    used_tags = set()
    for tag in request.GET.getlist('tag', []):
        entries = entries.filter(tags__slug=tag)
        used_tags.add(tag)

    try:
        year = int(request.GET.get('year'))
        entries = entries.filter(when__year=year)
    except (ValueError, TypeError):
        year = None

    try:
        month = int(request.GET.get('month'))
        entries = entries.filter(when__month=month)
    except (ValueError, TypeError):
        month = None

    try:
        who = request.GET.get('who', None)
    except (ValueError, TypeError):
        who = None
    if who:
        entries = entries.filter(who__username=who)

    all_years = book.years(entries)
    all_users = book.who(entries)
    all_tags = book.tags(entries)
    available_tags = set(str(i) for i in all_tags.keys()).difference(used_tags)
    entries = entries.order_by('-when', 'who')
    context = dict(
        entries=entries, book=book, year=year, month=month, who=who,
        all_years=all_years, all_users=all_users, all_tags=all_tags,
        available_tags=available_tags, used_tags=used_tags)

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
            entry = form.save(book=book)
            return HttpResponseRedirect(
                reverse(entries, kwargs=dict(book_slug=book_slug)))
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
        form = EntryForm(instance=entry,
                           initial=dict(who=who, currency=currency))

    all_years = book.years()
    all_users = book.who()
    all_tags = book.tags()
    context = dict(
        form=form, book=book, entry=entry,
        all_years=all_years, all_users=all_users, all_tags=all_tags)
    return render(request, 'gemcore/entry.html', context)


@require_http_methods(['GET', 'POST'])
@login_required
def entry_remove(request, book_slug, entry_id):
    entry = get_object_or_404(
        Entry, book__slug=book_slug, book__users=request.user, id=entry_id)
    return remove_thing(request, entry)
