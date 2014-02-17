from django import forms
from django.contrib.admin import widgets

from gemcore.models import Book, Currency, Expense


class BookForm(forms.ModelForm):

    class Meta:
        model = Book
        widgets = dict(
            users=forms.SelectMultiple(attrs={'class': 'form-control'}),
        )


class CurrencyForm(forms.ModelForm):

    class Meta:
        model = Currency


class ExpenseForm(forms.ModelForm):

    def save(self, *args, book, **kwargs):
        self.instance.book = book
        return super(ExpenseForm, self).save(*args, **kwargs)

    class Meta:
        model = Expense
        exclude = ('book',)
        widgets = dict(
            when=widgets.AdminDateWidget,
            what=forms.TextInput,
        )
