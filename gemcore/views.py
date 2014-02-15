from django.contrib.auth.decorators import login_required
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_http_methods

from gemcore.forms import BookForm, ExpenseForm
from gemcore.models import Expense


@require_GET
@login_required
def home(request):
    expenses = Expense.objects.filter(who=request.user).order_by('-when')[:10]
    books = request.user.book_set.all()
    return render(
        request, 'gemcore/home.html', dict(books=books, expenses=expenses))


@require_http_methods(['GET', 'POST'])
@login_required
def add_book(request):
    if request.method == 'POST':
        form = BookForm(request.POST)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(reverse(home))
    else:
        form = BookForm()
    return render(request, 'gemcore/book.html', dict(form=form))


@require_http_methods(['GET', 'POST'])
@login_required
def add_expense(request, book_id):
    book = get_object_or_404(Book, id=book_id)
    if request.method == 'POST':
        form = ExpenseForm(book=book, data=request.POST)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(reverse(home))
    else:
        form = ExpenseForm(book=book)
    return render(request, 'gemcore/expense.html', dict(form=form))
