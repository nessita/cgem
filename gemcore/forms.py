from django import forms
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
        if cleaned_data['is_income']:
            cleaned_data['tags'].append('income')
        else:
            cleaned_data['tags'].append('expense')
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
