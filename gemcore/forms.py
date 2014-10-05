from django import forms

from gemcore.models import Book, Entry


class BookForm(forms.ModelForm):

    class Meta:
        model = Book
        exclude = ('slug',)
        widgets = dict(
            users=forms.SelectMultiple(attrs={'class': 'form-control'}),
        )


class EntryForm(forms.ModelForm):

    def clean(self):
        cleaned_data = super(EntryForm, self).clean()
        if not cleaned_data['tags']:
            raise forms.ValidationError('Missing tags, choose at leas one.')
        return cleaned_data

    def save(self, *args, book, **kwargs):
        self.instance.book = book
        return super(EntryForm, self).save(*args, **kwargs)

    class Meta:
        model = Entry
        exclude = ('book', 'tags')
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
            country=forms.Select(
                attrs={'class': 'form-control', 'placeholder': 'where'}),
            notes=forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': 'notes'}),
        )


class CSVExpenseForm(forms.Form):

    csv_file = forms.FileField()
