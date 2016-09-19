import argparse

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from gemcore.models import Book
from gemcore.parse import PARSER_MAPPING


User = get_user_model()


class Command(BaseCommand):

    help = 'Parse a csv files of expense/income entries.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', dest='dry-run', default=False)
        parser.add_argument('--file', type=argparse.FileType('r'))
        parser.add_argument('--parser', choices=PARSER_MAPPING.keys())
        parser.add_argument(
            '--book',
            choices=Book.objects.all().values_list('slug', flat=True))

    def handle(self, *args, **options):
        book = Book.objects.get(slug=options['book'])
        expense_parser = PARSER_MAPPING[options['parser']](book)
        f = options['file']
        dry_run = options['dry-run']
        self.stdout.write(
            'Parsing (dry run %s) %s with %s' % (
                dry_run, f.name, expense_parser.__class__.__name__))
        result = expense_parser.parse(fileobj=f, dry_run=dry_run)
        for error, traceback in result['errors'].items():
            self.stdout.write('=== ERROR: %s ===' % error)
            self.stdout.write('\n'.join(str(i[0]) for i in traceback))
            self.stdout.write('\n\n')
