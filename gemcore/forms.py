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
        if not cleaned_data.get('tags'):
            raise forms.ValidationError('Missing tags, choose at leas one.')
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
            country=forms.Select(
                attrs={'class': 'form-control', 'placeholder': 'where'}),
            notes=forms.Textarea(
                attrs={'class': 'form-control', 'placeholder': 'notes',
                       'rows': 3}),
        )


class CSVExpenseForm(forms.Form):

    csv_file = forms.FileField(required=False)
    csv_content = forms.CharField(
        required=False,
        label='CSV content (optional, only used if not file given)',
        widget=forms.Textarea(attrs={'class': 'form-control'}))

    def clean(self):
        cleaned_data = super(CSVExpenseForm, self).clean()
        if (not cleaned_data.get('csv_file')
                and not cleaned_data.get('csv_content')):
            raise forms.ValidationError(
                'Either the CSV file or the CSV content should be set.')

        return cleaned_data
