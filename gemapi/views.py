from rest_framework import viewsets, mixins
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated

from gemapi.serializers import EntrySerializer
from gemcore.models import Entry


class AddEntryView(mixins.CreateModelMixin, viewsets.GenericViewSet):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    queryset = Entry.objects.none()
    serializer_class = EntrySerializer
