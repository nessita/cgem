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
def expenses(request, book_slug, tag_slug=None):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)
    if tag_slug:
        expenses = book.expense_set.filter(tags__slug=tag_slug)
    else:
        expenses = book.expense_set.all()

    expenses = expenses.order_by('-when', 'who')
    return render(
        request, 'gemcore/expenses.html',
        dict(expenses=expenses, book=book, tag=tag_slug))


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
            return HttpResponseRedirect(reverse(home))
    else:
        form = ExpenseForm(instance=expense, initial=dict(who=request.user))
    return render(
        request, 'gemcore/expense.html',
        dict(form=form, book=book, expense=expense))


@require_http_methods(['GET', 'POST'])
@login_required
def expense_remove(request, book_slug, expense_id):
    expense = get_object_or_404(
        Expense, book__slug=book_slug, book__users=request.user, id=expense_id)
    return remove_thing(request, expense)
