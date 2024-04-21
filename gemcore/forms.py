from datetime import date

from django import forms
from django.db import IntegrityError, transaction
from django_countries import countries

from gemcore.constants import ChoicesMixin
from gemcore.models import Account, Asset, Book, Entry


class ChooseForm(forms.Form):
    def __init__(self, queryset=None, choices=None, *args, **kwargs):
        super(ChooseForm, self).__init__(*args, **kwargs)
        if choices:
            self.fields["target"] = forms.ChoiceField(
                label="Choices",
                choices=choices,
                required=False,
                widget=forms.Select(attrs={"class": "form-control input-sm"}),
            )
        else:
            self.fields["target"] = forms.ModelChoiceField(
                label="Choices",
                queryset=queryset,
                required=False,
                widget=forms.Select(attrs={"class": "form-control input-sm"}),
            )


class BalanceForm(forms.Form):
    start = forms.DateField(
        widget=forms.DateInput(
            attrs={
                "class": "form-control input-sm datepicker",
                "placeholder": "Start",
            }
        ),
        required=False,
    )
    end = forms.DateField(
        widget=forms.DateInput(
            attrs={
                "class": "form-control input-sm datepicker",
                "placeholder": "End",
            }
        ),
        required=False,
    )


class AccountBalanceForm(BalanceForm):
    source = forms.ModelChoiceField(
        label="Account",
        queryset=None,
        widget=forms.Select(attrs={"class": "form-control input-sm"}),
    )

    def __init__(self, queryset, *args, **kwargs):
        super(AccountBalanceForm, self).__init__(*args, **kwargs)
        self.fields["source"].queryset = queryset
        initial = kwargs.get("initial", {}).get("source")
        if initial:
            self.fields["source"].initial = queryset.get(slug=initial).pk


class CurrencyBalanceForm(BalanceForm):
    source = forms.ChoiceField(
        label="Currency",
        widget=forms.Select(attrs={"class": "form-control input-sm"}),
    )

    def __init__(self, choices, *args, **kwargs):
        super(CurrencyBalanceForm, self).__init__(*args, **kwargs)
        self.fields["source"].choices = [(i, i) for i in choices]
        self.fields["source"].initial = kwargs.get("initial", {}).get("source")


class BookForm(forms.ModelForm):
    class Meta:
        model = Book
        exclude = ("slug",)
        widgets = dict(
            users=forms.SelectMultiple(attrs={"class": "form-control"})
        )


class TagsCheckboxSelectMultiple(forms.CheckboxSelectMultiple):
    option_template_name = "gemcore/checkbox_option.html"


class EntryForm(forms.ModelForm):
    def __init__(self, book, *args, **kwargs):
        self.book = book
        super(EntryForm, self).__init__(*args, **kwargs)
        self.fields["account"].queryset = Account.objects.by_book(book)
        self.fields["asset"].queryset = Asset.objects.by_book(book)
        self.fields["tags"] = forms.MultipleChoiceField(
            choices=ChoicesMixin.TAG_CHOICES,
            widget=TagsCheckboxSelectMultiple(),
        )

    def clean(self):
        cleaned_data = super(EntryForm, self).clean()
        if not cleaned_data.get("tags"):
            raise forms.ValidationError("Missing tags, choose at least one.")
        return cleaned_data

    @transaction.atomic
    def save(self, *args, **kwargs):
        self.instance.book = self.book
        try:
            self.instance = super(EntryForm, self).save(*args, **kwargs)
        except IntegrityError:
            self.instance = None
            self.add_error(None, "There is already an entry for this data.")
        return self.instance

    class Meta:
        model = Entry
        exclude = ("book",)
        widgets = dict(
            when=forms.DateInput(attrs={"class": "form-control datepicker"}),
            who=forms.Select(
                attrs={"class": "form-control", "placeholder": "who"}
            ),
            what=forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "what",
                    "autofocus": "true",
                }
            ),
            amount=forms.NumberInput(
                attrs={
                    "size": 10,
                    "class": "form-control",
                    "placeholder": "how much",
                }
            ),
            account=forms.Select(attrs={"class": "form-control"}),
            asset=forms.Select(attrs={"class": "form-control"}),
            country=forms.Select(
                attrs={"class": "form-control", "placeholder": "where"}
            ),
            notes=forms.Textarea(
                attrs={
                    "class": "form-control",
                    "placeholder": "notes",
                    "rows": 3,
                }
            ),
        )


class EntryMergeForm(forms.Form):
    when = forms.DateField(
        widget=forms.DateInput(
            attrs={"class": "form-control input-sm datepicker"}
        )
    )


class CSVExpenseForm(forms.Form):
    account = forms.ModelChoiceField(
        label="Account",
        queryset=Account.objects.none(),
        widget=forms.Select(
            attrs={"class": "form-control", "autofocus": "true"}
        ),
    )
    csv_file = forms.FileField(required=False)
    csv_content = forms.CharField(
        required=False,
        label="CSV content (optional, only used if not file given)",
        widget=forms.Textarea(attrs={"class": "form-control"}),
    )

    def __init__(self, book, *args, **kwargs):
        super(CSVExpenseForm, self).__init__(*args, **kwargs)
        accounts = Account.objects.by_book(book).exclude(parser_config=None)
        self.fields["account"].queryset = accounts.select_related(
            "parser_config"
        ).prefetch_related("tagregex_set")

    def clean(self):
        data = super(CSVExpenseForm, self).clean()
        if not (data.get("csv_file") or data.get("csv_content")):
            raise forms.ValidationError(
                "Either the CSV file or the CSV content should be set."
            )
        return data


class AccountTransferForm(forms.Form):
    source_account = forms.ModelChoiceField(
        label="From",
        queryset=Account.objects.none(),
        widget=forms.Select(
            attrs={"class": "form-control", "autofocus": "true"}
        ),
    )
    source_amount = forms.DecimalField(
        label="$",
        min_value=0.1,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )
    target_account = forms.ModelChoiceField(
        label="To",
        queryset=Account.objects.none(),
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    target_amount = forms.DecimalField(
        label="$",
        min_value=0.1,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )
    what = forms.CharField(
        initial="Traspaso de fondos",
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "what"}
        ),
    )
    when = forms.DateField(
        initial=date.today(),
        widget=forms.DateInput(attrs={"class": "form-control datepicker"}),
    )
    country = forms.ChoiceField(
        choices=countries,
        initial="UY",
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    def __init__(self, book, *args, **kwargs):
        super(AccountTransferForm, self).__init__(*args, **kwargs)
        accounts = Account.objects.by_book(book)
        self.fields["source_account"].queryset = accounts
        self.fields["target_account"].queryset = accounts

    def clean(self):
        cleaned_data = super(AccountTransferForm, self).clean()
        source = cleaned_data.get("source_account")
        target = cleaned_data.get("target_account")
        if source == target:
            raise forms.ValidationError(
                "Source account can not be the same as the target account."
            )

        return cleaned_data
