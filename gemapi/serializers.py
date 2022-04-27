from rest_framework import serializers

from gemcore.models import Account, Book, Entry, User


class EntrySerializer(serializers.ModelSerializer):

    book = serializers.SlugRelatedField(
        slug_field='slug', queryset=Book.objects.all()
    )
    account = serializers.SlugRelatedField(
        slug_field='slug', queryset=Account.objects.all()
    )
    who = serializers.SlugRelatedField(
        slug_field='username', queryset=User.objects.all()
    )

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
