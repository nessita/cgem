from rest_framework import serializers

from gemcore.models import Entry


class EntrySerializer(serializers.ModelSerializer):

    class Meta:
        model = Entry
        fields = ('when', 'what', 'amount', 'is_income')
