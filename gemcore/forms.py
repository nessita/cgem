from datetime import date

from django import forms
from django.db import IntegrityError, transaction
from django_countries import countries

from gemcore.models import TAGS, Account, Book, Entry


class ChooseForm(forms.Form):

    target = forms.ModelChoiceField(
        label='Choices',
        queryset=None,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control input-sm'}),
    )

    def __init__(self, queryset, *args, **kwargs):
        super(ChooseForm, self).__init__(*args, **kwargs)
        self.fields['target'].queryset = queryset


class BalanceForm(forms.Form):

    start = forms.DateField(
        widget=forms.DateInput(
            attrs={
                'class': 'form-control input-sm datepicker',
                'placeholder': 'Start',
            }
        ),
        required=False,
    )
    end = forms.DateField(
        widget=forms.DateInput(
            attrs={
                'class': 'form-control input-sm datepicker',
                'placeholder': 'End',
            }
        ),
        required=False,
    )


class AccountBalanceForm(BalanceForm):

    source = forms.ModelChoiceField(
        label='Account',
        queryset=None,
        widget=forms.Select(attrs={'class': 'form-control input-sm'}),
    )

    def __init__(self, queryset, *args, **kwargs):
        super(AccountBalanceForm, self).__init__(*args, **kwargs)
        self.fields['source'].queryset = queryset
        initial = kwargs.get('initial', {}).get('source')
        if initial:
            self.fields['source'].initial = queryset.get(slug=initial).pk


class CurrencyBalanceForm(BalanceForm):

    source = forms.ChoiceField(
        label='Currency',
        widget=forms.Select(attrs={'class': 'form-control input-sm'}),
    )

    def __init__(self, choices, *args, **kwargs):
        super(CurrencyBalanceForm, self).__init__(*args, **kwargs)
        self.fields['source'].choices = [(i, i) for i in choices]
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
        self.fields['tags'] = forms.MultipleChoiceField(
            choices=((i, i) for i in TAGS),
            widget=forms.CheckboxSelectMultiple(),
        )

    def clean(self):
        cleaned_data = super(EntryForm, self).clean()
        if not cleaned_data.get('tags'):
            raise forms.ValidationError('Missing tags, choose at least one.')
        return cleaned_data

    @transaction.atomic
    def save(self, *args, book, **kwargs):
        self.instance.book = book
        try:
            self.instance = super(EntryForm, self).save(*args, **kwargs)
        except IntegrityError:
            self.instance = None
            self.add_error(None, 'There is already an entry for this data.')
        return self.instance

    class Meta:
        model = Entry
        exclude = ('book',)
        widgets = dict(
            when=forms.DateInput(attrs={'class': 'form-control datepicker'}),
            who=forms.Select(
                attrs={'class': 'form-control', 'placeholder': 'who'}
            ),
            what=forms.TextInput(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'what',
                    'autofocus': 'true',
                }
            ),
            amount=forms.NumberInput(
                attrs={
                    'size': 10,
                    'class': 'form-control',
                    'placeholder': 'how much',
                }
            ),
            account=forms.Select(attrs={'class': 'form-control'}),
            country=forms.Select(
                attrs={'class': 'form-control', 'placeholder': 'where'}
            ),
            notes=forms.Textarea(
                attrs={
                    'class': 'form-control',
                    'placeholder': 'notes',
                    'rows': 3,
                }
            ),
        )


class EntryMergeForm(forms.Form):

    when = forms.DateField(
        widget=forms.DateInput(
            attrs={'class': 'form-control input-sm datepicker'}
        )
    )


class CSVExpenseForm(forms.Form):

    account = forms.ModelChoiceField(
        label='Account',
        queryset=Account.objects.none(),
        widget=forms.Select(
            attrs={'class': 'form-control', 'autofocus': 'true'}
        ),
    )
    csv_file = forms.FileField(required=False)
    csv_content = forms.CharField(
        required=False,
        label='CSV content (optional, only used if not file given)',
        widget=forms.Textarea(attrs={'class': 'form-control'}),
    )

    def __init__(self, book, *args, **kwargs):
        super(CSVExpenseForm, self).__init__(*args, **kwargs)
        accounts = Account.objects.by_book(book).exclude(parser_config=None)
        self.fields['account'].queryset = accounts

    def clean(self):
        data = super(CSVExpenseForm, self).clean()
        if not (data.get('csv_file') or data.get('csv_content')):
            raise forms.ValidationError(
                'Either the CSV file or the CSV content should be set.'
            )
        return data


class AccountTransferForm(forms.Form):

    source_account = forms.ModelChoiceField(
        label='From',
        queryset=Account.objects.none(),
        widget=forms.Select(
            attrs={'class': 'form-control', 'autofocus': 'true'}
        ),
    )
    source_amount = forms.DecimalField(
        label='$',
        min_value=0.1,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
    )
    target_account = forms.ModelChoiceField(
        label='To',
        queryset=Account.objects.none(),
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    target_amount = forms.DecimalField(
        label='$',
        min_value=0.1,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
    )
    what = forms.CharField(
        initial='Traspaso de fondos',
        widget=forms.TextInput(
            attrs={'class': 'form-control', 'placeholder': 'what'}
        ),
    )
    when = forms.DateField(
        initial=date.today(),
        widget=forms.DateInput(attrs={'class': 'form-control datepicker'}),
    )
    country = forms.ChoiceField(
        choices=countries,
        initial='UY',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    def __init__(self, book, *args, **kwargs):
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
                'Source account can not be the same as the target account.'
            )

        return cleaned_data
