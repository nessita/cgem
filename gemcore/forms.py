from datetime import date

from django import forms
from django_countries import countries

from gemcore.models import Account, Book, Entry


class BalanceForm(forms.Form):

    start = forms.DateField(
        widget=forms.DateInput(
            attrs={'class': 'form-control input-sm datepicker',
                   'placeholder': 'Start'}),
        required=False)
    end = forms.DateField(
        widget=forms.DateInput(
            attrs={'class': 'form-control input-sm datepicker',
                   'placeholder': 'End'}),
        required=False)


class AccountBalanceForm(BalanceForm):

    source = forms.ModelChoiceField(
        label='Account', queryset=None,
        widget=forms.Select(attrs={'class': 'form-control input-sm',
                                   'autofocus': 'true'}))

    def __init__(self, book, *args, **kwargs):
        super(BalanceForm, self).__init__(*args, **kwargs)
        self.fields['source'].queryset = Account.objects.by_book(book)


class CurrencyBalanceForm(BalanceForm):

    source = forms.ChoiceField(
        label='Currency',
        widget=forms.Select(attrs={'class': 'form-control input-sm',
                                   'autofocus': 'true'}))

    def __init__(self, book, *args, **kwargs):
        super(BalanceForm, self).__init__(*args, **kwargs)
        accounts = Account.objects.by_book(book)
        self.fields['source'].choices = [
            (i, i) for i in
            sorted(set(accounts.values_list('currency_code', flat=True)))]
        self.fields['source'].initial = kwargs.get('initial', {}).get('source')


class BookForm(forms.ModelForm):

    class Meta:
        model = Book
        exclude = ('slug',)
        widgets = dict(
            users=forms.SelectMultiple(attrs={'class': 'form-control'}),
        )


class EntryForm(forms.ModelForm):

    def __init__(self, book, *args, **kwargs):
        super(EntryForm, self).__init__(*args, **kwargs)
        self.fields['account'].queryset = Account.objects.by_book(book)

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
            amount=forms.NumberInput(
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

    source = forms.ChoiceField(
        choices=(
            ('disc-bank', 'DISC Bank'),
            ('wfg-bank', 'WFG Bank'),
            ('trips', 'Trips'),
            ('expense', 'Expense'),
        ),
        widget=forms.Select(
            attrs={'class': 'form-control', 'autofocus': 'true'})
    )
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


class AccountTransferForm(forms.Form):

    source_account = forms.ModelChoiceField(
        label='From', queryset=Account.objects.none(),
        widget=forms.Select(
            attrs={'class': 'form-control', 'autofocus': 'true'}),
    )
    source_amount = forms.DecimalField(
        label='$', min_value=0.1, decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
    )
    target_account = forms.ModelChoiceField(
        label='To', queryset=Account.objects.none(),
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    target_amount = forms.DecimalField(
        label='$', min_value=0.1, decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
    )
    what = forms.CharField(
        initial='Traspaso de fondos',
        widget=forms.TextInput(
            attrs={'class': 'form-control', 'placeholder': 'what'}))
    when = forms.DateField(
        initial=date.today(),
        widget=forms.DateInput(attrs={'class': 'form-control datepicker'}),
    )
    country = forms.ChoiceField(
        choices=countries, initial='UY',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    def __init__(self, user, book, *args, **kwargs):
        super(AccountTransferForm, self).__init__(*args, **kwargs)
        accounts = Account.objects.by_book(book)
        self.fields['source_account'].queryset = accounts
        self.fields['target_account'].queryset = accounts

    def clean(self):
        cleaned_data = super(AccountTransferForm, self).clean()
        source = cleaned_data.get('source_account')
        target = cleaned_data.get('target_account')
        if source == target:
            raise forms.ValidationError(
                'Source account can not be the same as the target account.')

        return cleaned_data
