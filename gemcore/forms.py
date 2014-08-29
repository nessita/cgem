from django import forms
from taggit.forms import TagField, TagWidget

from gemcore.models import Book, Currency, Expense


class BookForm(forms.ModelForm):

    class Meta:
        model = Book
        exclude = ('slug',)
        widgets = dict(
            users=forms.SelectMultiple(attrs={'class': 'form-control'}),
        )


class CurrencyForm(forms.ModelForm):

    class Meta:
        model = Currency


class ExpenseForm(forms.ModelForm):

    tags = TagField(widget=TagWidget(
        attrs={'class': 'form-control', 'placeholder': 'tags'}))

    def save(self, *args, book, **kwargs):
        self.instance.book = book
        return super(ExpenseForm, self).save(*args, **kwargs)

    class Meta:
        model = Expense
        exclude = ('book',)
        widgets = dict(
            when=forms.DateInput(
                attrs={'class': 'form-control datepicker'}),
            who=forms.Select(
                attrs={'class': 'form-control', 'placeholder': 'who'}),
            what=forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': 'what',
                       'autofocus': 'true'}),
            amount=forms.TextInput(
                attrs={'size': 10, 'class': 'form-control',
                       'placeholder': 'how much'}),
            account=forms.Select(attrs={'class': 'form-control'}),
        )
