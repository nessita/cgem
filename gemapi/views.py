import io

from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from gemapi.serializers import EntrySerializer
from gemcore.models import Account, Book
from gemcore.parser import CSVParser


TEST_SLUG = 'test'


class EntryViewSet(viewsets.ModelViewSet):

    serializer_class = EntrySerializer

    def get_queryset(self):
        book = Book.objects.get(slug=TEST_SLUG)
        return book.entry_set.all().order_by('when')


@api_view(['POST'])
def transactions(request):
    book = get_object_or_404(Book, slug=TEST_SLUG)
    account = get_object_or_404(Account, slug=TEST_SLUG)
    user = User.objects.get(username=TEST_SLUG)

    f = request.FILES.get('data')
    errors = []
    if not f:
        return Response({'errors': ['Please upload a data file']})

    stream = io.StringIO(f.read().decode('utf-8'), newline=None)
    stream.name = 'data.csv'
    result = CSVParser(account).parse(stream, book=book, user=user)
    errors = [
        '%s: %s' % (k, str(v[0]))
        for k, vs in result['errors'].items() for v in vs]
    return Response({'errors': errors})


@api_view(['GET'])
def report(request):
    book = get_object_or_404(Book, slug=TEST_SLUG)
    balance = book.calculate_balance()
    if balance is not None:
        report = {
            'net-revenue': balance['result'],
            'gross-revenue': balance['income'],
            'expenses': balance['expense'],
        }
    else:
        report = {}
    return Response(report)
