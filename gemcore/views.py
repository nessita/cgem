from django.contrib.auth.decorators import login_required
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_http_methods

from gemcore.forms import BookForm, ExpenseForm
from gemcore.models import Book, Expense


@require_GET
@login_required
def home(request):
    expenses = Expense.objects.filter(who=request.user).order_by('-when')[:10]
    books = request.user.book_set.all()
    return render(
        request, 'gemcore/home.html', dict(books=books, expenses=expenses))


@require_http_methods(['GET', 'POST'])
@login_required
def book(request, book_id=None):
    book = None
    if book_id:
        book = get_object_or_404(Book, id=book_id)

    if request.method == 'POST':
        form = BookForm(instance=book, data=request.POST)
        if form.is_valid():
            book = form.save()
            if 'save-and-add-expense' in request.POST:
                redirect = reverse('add-expense', kwargs=dict(book_id=book.id))
            elif 'save' in request.POST:
                redirect = '.'
            else:
                redirect = reverse(home)

            return HttpResponseRedirect(redirect)
    else:
        form = BookForm(instance=book)
    return render(request, 'gemcore/book.html', dict(form=form, book=book))


@require_http_methods(['GET', 'POST'])
@login_required
def book_remove(request, book_id):
    book = get_object_or_404(Book, id=book_id)

    if request.method == 'POST':
        if 'yes' in request.POST:
            book.delete()
        return HttpResponseRedirect(reverse(home))

    return render(request, 'gemcore/book_remove.html', dict(book=book))


@require_http_methods(['GET', 'POST'])
@login_required
def expense(request, book_id):
    book = get_object_or_404(Book, id=book_id)
    if request.method == 'POST':
        form = ExpenseForm(data=request.POST)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.book = book
            expense.save()
            return HttpResponseRedirect(reverse(home))
    else:
        form = ExpenseForm(initial=dict(book=book, who=request.user))
    return render(request, 'gemcore/expense.html', dict(form=form))
