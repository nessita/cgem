from django import forms
from django.db import IntegrityError, transaction
from django_countries import countries

from gemcore.constants import ChoicesMixin
from gemcore.models import Account, Asset, Book, Entry, utc_today


class ChooseForm(forms.Form):
    def __init__(
        self, queryset=None, choices=None, *args, label="Choices", **kwargs
    ):
        super(ChooseForm, self).__init__(*args, **kwargs)
        placeholder = f"Choose {label.lower()}..."
        if choices:
            self.fields["target"] = forms.ChoiceField(
                label=label,
                choices=[("", placeholder), *choices],
                required=False,
            )
        else:
            self.fields["target"] = forms.ModelChoiceField(
                label=label,
                queryset=queryset,
                required=False,
                empty_label=placeholder,
            )


class BalanceForm(forms.Form):
    start = forms.DateField(
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={
                "placeholder": "Start",
                "type": "date",
            },
        ),
        required=False,
    )
    end = forms.DateField(
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={
                "placeholder": "End",
                "type": "date",
            },
        ),
        required=False,
    )


class AccountBalanceForm(BalanceForm):
    source = forms.ModelChoiceField(
        label="Account",
        queryset=None,
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
    )

    def __init__(self, choices, *args, **kwargs):
        super(CurrencyBalanceForm, self).__init__(*args, **kwargs)
        self.fields["source"].choices = [(i, i) for i in choices]
        self.fields["source"].initial = kwargs.get("initial", {}).get("source")


class BookForm(forms.ModelForm):
    class Meta:
        model = Book
        exclude = ("slug",)


class EntryForm(forms.ModelForm):
    def __init__(self, book, *args, **kwargs):
        self.book = book
        data = kwargs.get("data")
        if data is not None:
            data = data.copy()
            if hasattr(data, "getlist"):
                tags = [tag for tag in data.getlist("tags") if tag]
            else:
                tags = data.get("tags")
                if isinstance(tags, str):
                    tags = [tags] if tags else []
                elif isinstance(tags, (list, tuple)):
                    tags = [tag for tag in tags if tag]
                else:
                    tags = []
            if len(tags) > 1:
                raise ValueError("EntryForm expects exactly one tag.")
            data["tags"] = tags[0] if tags else ""
            kwargs["data"] = data
        super(EntryForm, self).__init__(*args, **kwargs)
        self.fields["account"].queryset = Account.objects.by_book(book)
        self.fields["asset"].queryset = Asset.objects.by_book(book)
        self.fields["tags"] = forms.ChoiceField(
            label="Tag",
            choices=ChoicesMixin.TAG_CHOICES,
            widget=forms.RadioSelect(),
        )
        self.fields["tags"].widget.template_name = "forms/radio.html"
        self.fields["tags"].widget.option_template_name = (
            "forms/radio_option.html"
        )
        if self.instance.pk and len(self.instance.tags) > 1:
            raise ValueError("Entry instances must not have multiple tags.")
        if self.instance.pk and self.instance.tags:
            self.initial["tags"] = self.instance.tags[0]

    def clean_tags(self):
        value = self.cleaned_data["tags"]

        if not value:
            raise forms.ValidationError("Missing tags, choose at least one.")

        if isinstance(value, str):
            return [value]

        if isinstance(value, (list, tuple)):
            if len(value) != 1:
                raise forms.ValidationError("Choose exactly one tag.")
            return list(value)

        raise forms.ValidationError("Invalid tag value.")

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
            when=forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date"},
            ),
            who=forms.Select(attrs={"placeholder": "who"}),
            what=forms.TextInput(
                attrs={
                    "placeholder": "what",
                    "autofocus": "true",
                }
            ),
            amount=forms.NumberInput(
                attrs={
                    "size": 10,
                    "placeholder": "how much",
                }
            ),
            country=forms.Select(attrs={"placeholder": "where"}),
            notes=forms.Textarea(
                attrs={
                    "placeholder": "notes",
                    "rows": 2,
                }
            ),
        )


class EntryMergeForm(forms.Form):
    when = forms.DateField(
        widget=forms.DateInput(
            format="%Y-%m-%d",
            attrs={"type": "date"},
        )
    )


class CSVExpenseForm(forms.Form):
    account = forms.ModelChoiceField(
        label="Account",
        queryset=Account.objects.none(),
        widget=forms.Select(attrs={"autofocus": "true"}),
    )
    csv_file = forms.FileField(required=False)
    csv_content = forms.CharField(
        required=False,
        label="CSV content (optional, only used if not file given)",
        widget=forms.Textarea(),
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
        widget=forms.Select(attrs={"autofocus": "true"}),
    )
    source_amount = forms.DecimalField(
        label="$",
        min_value=0.1,
        decimal_places=2,
    )
    target_account = forms.ModelChoiceField(
        label="To",
        queryset=Account.objects.none(),
    )
    target_amount = forms.DecimalField(
        label="$",
        min_value=0.1,
        decimal_places=2,
    )
    what = forms.CharField(
        initial="Traspaso de fondos",
        widget=forms.TextInput(attrs={"placeholder": "what"}),
    )
    when = forms.DateField(
        initial=utc_today,
        widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
    )
    country = forms.ChoiceField(
        choices=countries,
        initial="UY",
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
