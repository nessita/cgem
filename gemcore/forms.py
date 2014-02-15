from django import forms

from gemcore.models import Book, Currency, Expense


class BookForm(forms.ModelForm):

    class Meta:
        model = Book


class CurrencyForm(forms.ModelForm):

    class Meta:
        model = Currency



class ExpenseForm(forms.ModelForm):

    class Meta:
        model = Expense
