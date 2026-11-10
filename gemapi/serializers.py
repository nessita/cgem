from django.conf import settings
from django.db import IntegrityError, transaction
from rest_framework import serializers

from gemcore.constants import ChoicesMixin, get_tag_choices
from gemcore.models import Account, Entry


class BackwardCompatibleTagField(serializers.ChoiceField):
    def to_internal_value(self, data):
        if isinstance(data, str):
            labels = {label.lower(): code for code, label in get_tag_choices()}
            data = labels.get(data.lower(), data)
        return super().to_internal_value(data)


class SelectedBookDefault:
    requires_context = True

    def __call__(self, serializer_field):
        return serializer_field.context["book"]


class EntrySerializer(serializers.ModelSerializer):
    book = serializers.SlugRelatedField(
        slug_field="slug", read_only=True, default=SelectedBookDefault()
    )
    account = serializers.SlugRelatedField(
        slug_field="slug", queryset=Account.objects.none()
    )
    who = serializers.ReadOnlyField(source="who.username")

    def get_fields(self):
        fields = super().get_fields()
        fields["tags"].child.choices = get_tag_choices()
        return fields

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        book = self.context.get("book")
        if book is not None:
            self.fields["account"].queryset = Account.objects.by_book(book)

    def validate(self, data):
        book = self.context["book"]
        if (
            self.context.get("book_slug")
            and "book" in self.initial_data
            and self.initial_data["book"] != book.slug
        ):
            raise serializers.ValidationError(
                {"book": "The entry book must match the selected book."}
            )
        data["book"] = book
        tags = data.get("tags")
        if tags is None:
            tags = list(data["account"].tags_for(data["what"]))
        tags = tags or [settings.ENTRY_TAGS["default"]]
        if len(tags) != 1:
            raise serializers.ValidationError(
                {"tags": "Choose exactly one tag."}
            )
        data["tags"] = tags
        return data

    def create(self, validated_data):
        try:
            with transaction.atomic():
                return super().create(validated_data)
        except IntegrityError:
            # A concurrent request can insert a duplicate after validation.
            unique_fields = Entry._meta.unique_together[0]
            lookup = {name: validated_data[name] for name in unique_fields}
            if Entry.objects.filter(**lookup).exists():
                raise serializers.ValidationError(
                    {
                        "non_field_errors": [
                            "There is already an entry for this data."
                        ]
                    }
                ) from None
            raise

    class Meta:
        model = Entry
        fields = [
            "id",
            "book",
            "account",
            "who",
            "when",
            "what",
            "amount",
            "is_income",
            "tags",
            "country",
            "notes",
        ]
        extra_kwargs = {
            "tags": {
                "allow_empty": False,
                "min_length": 1,
                "max_length": 1,
                "child": BackwardCompatibleTagField(choices=()),
            }
        }


class EntryFilterSerializer(serializers.Serializer):
    account = serializers.CharField(required=False)
    start = serializers.DateField(required=False, input_formats=["%Y-%m-%d"])
    end = serializers.DateField(required=False, input_formats=["%Y-%m-%d"])
    country = serializers.ChoiceField(
        choices=ChoicesMixin.COUNTRY_CHOICES, required=False, allow_blank=True
    )
    currency = serializers.ChoiceField(
        choices=ChoicesMixin.CURRENCY_CHOICES, required=False
    )
    who = serializers.CharField(required=False)
    tag = serializers.ListField(
        child=BackwardCompatibleTagField(choices=()),
        required=False,
    )
    is_income = serializers.BooleanField(required=False)
    page = serializers.IntegerField(required=False, min_value=1)
    page_size = serializers.IntegerField(
        required=False, min_value=1, max_value=100
    )

    def get_fields(self):
        fields = super().get_fields()
        fields["tag"].child.choices = get_tag_choices()
        return fields

    def to_internal_value(self, data):
        # Query parameters must not use HTML's missing-checkbox=False rule.
        values = data.dict()
        if "tag" in data:
            values["tag"] = data.getlist("tag")
        return super().to_internal_value(values)

    def validate(self, data):
        errors = {}
        for name in self.initial_data:
            if name not in self.fields:
                errors[name] = "Unknown query parameter."
            elif name != "tag" and len(self.initial_data.getlist(name)) > 1:
                errors[name] = "Provide this query parameter only once."
        if (
            data.get("start")
            and data.get("end")
            and data["start"] > data["end"]
        ):
            errors["end"] = "End must be on or after start."
        if errors:
            raise serializers.ValidationError(errors)
        return data
