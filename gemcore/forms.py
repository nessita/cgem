from django import forms
from django_countries.data import COUNTRIES
from taggit.forms import TagField, TagWidget

from gemcore.models import Book, Entry


class BookForm(forms.ModelForm):

    class Meta:
        model = Book
        exclude = ('slug',)
        widgets = dict(
            users=forms.SelectMultiple(attrs={'class': 'form-control'}),
        )


class EntryForm(forms.ModelForm):

    tags = TagField(widget=TagWidget(
        attrs={'class': 'form-control', 'placeholder': 'tags'}))

    def clean(self):
        cleaned_data = super(EntryForm, self).clean()
        tags = cleaned_data.get('tags', [])

        # auto tag: country
        if not any(c in tags for c in COUNTRIES):
            account = cleaned_data.get('account')
            if account and account.currency_code == 'UYU':
                tags.append('UY')
            elif account and account.currency_code == 'ARS':
                tags.append('AR')
            else:
                raise forms.ValidationError('Missing country in tags.')

        return cleaned_data

    def save(self, *args, book, **kwargs):
        self.instance.book = book
        return super(EntryForm, self).save(*args, **kwargs)

    class Meta:
        model = Entry
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


class CSVExpenseForm(forms.Form):

    csv_file = forms.FileField()
