import subprocess

from rest_framework import viewsets, mixins
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from gemapi.serializers import EntrySerializer
from gemcore.models import Entry


class AddEntryView(mixins.CreateModelMixin, viewsets.GenericViewSet):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    queryset = Entry.objects.none()
    serializer_class = EntrySerializer

    # https://www.django-rest-framework.org/tutorial/\
    # 4-authentication-and-permissions/#associating-snippets-with-users
    def perform_create(self, serializer):
        serializer.save(who=self.request.user)


class VersionView(APIView):

    def get(self, request, format=None):
        git_hash = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD']).decode('ascii').strip()
        return Response(git_hash)
