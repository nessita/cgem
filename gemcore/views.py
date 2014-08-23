from django.contrib.auth.decorators import login_required
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_http_methods

from gemcore.forms import BookForm, ExpenseForm
from gemcore.models import Book, Expense


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
def expenses(request, book_slug):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)
    expenses = book.expense_set.all()

    used_tags = set()
    for tag in request.GET.getlist('tag', []):
        expenses = expenses.filter(tags__slug=tag)
        used_tags.add(tag)

    try:
        year = int(request.GET.get('year'))
        expenses = expenses.filter(when__year=year)
    except (ValueError, TypeError):
        year = None

    try:
        month = int(request.GET.get('month'))
        expenses = expenses.filter(when__month=month)
    except (ValueError, TypeError):
        month = None

    try:
        who = request.GET.get('who', None)
    except (ValueError, TypeError):
        who = None
    if who:
        expenses = expenses.filter(who__username=who)

    all_years = book.years(expenses)
    all_users = book.who(expenses)
    all_tags = book.tags(expenses)
    available_tags = set(str(i) for i in all_tags.keys()).difference(used_tags)
    expenses = expenses.order_by('-when', 'who')
    context = dict(
        expenses=expenses, book=book, all_years=all_years, all_users=all_users,
        all_tags=all_tags, available_tags=available_tags, used_tags=used_tags,
        year=year, month=month, who=who)

    return render(request, 'gemcore/expenses.html', context)


@require_http_methods(['GET', 'POST'])
@login_required
def expense(request, book_slug, expense_id=None):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)
    expense = None
    if expense_id:
        expense = get_object_or_404(Expense, book=book, id=expense_id)

    if request.method == 'POST':
        form = ExpenseForm(instance=expense, data=request.POST)
        if form.is_valid():
            expense = form.save(book=book)
            return HttpResponseRedirect(
                reverse(expenses, kwargs=dict(book_slug=book_slug)))
    else:
        currency = None
        who = request.user
        if expense is None:
            try:
                last_expense = Expense.objects.filter(
                    who=request.user, book=book).latest('when')
                currency = last_expense.currency
            except Expense.DoesNotExist:
                pass
        else:
            who = expense.who
        form = ExpenseForm(instance=expense,
                           initial=dict(who=who, currency=currency))
    return render(
        request, 'gemcore/expense.html',
        dict(form=form, book=book, expense=expense))


@require_http_methods(['GET', 'POST'])
@login_required
def expense_remove(request, book_slug, expense_id):
    expense = get_object_or_404(
        Expense, book__slug=book_slug, book__users=request.user, id=expense_id)
    return remove_thing(request, expense)
