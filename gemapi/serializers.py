from rest_framework import serializers

from django.conf import settings

from gemcore.constants import REVERSED_TAGS, ChoicesMixin
from gemcore.models import Account, Book, Entry


class BackwardCompatibleTagField(serializers.ChoiceField):
    def to_internal_value(self, data):
        data = REVERSED_TAGS.get(data.lower(), data)
        return super().to_internal_value(data)


class EntrySerializer(serializers.ModelSerializer):
    book = serializers.SlugRelatedField(
        slug_field='slug', queryset=Book.objects.all()
    )
    account = serializers.SlugRelatedField(
        slug_field='slug', queryset=Account.objects.all()
    )
    who = serializers.ReadOnlyField(source='who.username')

    def validate(self, data):
        tags = data.get('tags')
        if tags is None:
            tags = data['account'].tags_for(data['what']).keys()
        data['tags'] = tags or [settings.ENTRY_DEFAULT_TAG]
        return data

    class Meta:
        model = Entry
        fields = [
            'book',
            'account',
            'who',
            'when',
            'what',
            'amount',
            'is_income',
            'tags',
            'country',
            'notes',
        ]
        extra_kwargs = {
            'tags': {
                'child': BackwardCompatibleTagField(
                    choices=ChoicesMixin.TAG_CHOICES
                )
            }
        }
