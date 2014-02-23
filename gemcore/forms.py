from django import forms

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
            when=forms.DateInput(attrs={'class': 'form-control datepicker'}),
            who=forms.Select(
                attrs={'class': 'form-control', 'placeholder': 'who'}),
            what=forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': 'what'}),
            amount=forms.TextInput(
                attrs={'size': 10, 'class': 'form-control',
                       'placeholder': 'how much'}),
            currency=forms.Select(attrs={'class': 'form-control'}),
            tags=forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': 'tags'}),
        )
