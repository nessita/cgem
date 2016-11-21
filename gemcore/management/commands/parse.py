import argparse

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from gemcore.models import Account, Book
from gemcore.parse import PARSER_MAPPING


User = get_user_model()


class Command(BaseCommand):

    help = 'Parse a csv files of expense/income entries.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', dest='dry-run', default=False)
        parser.add_argument('--file', type=argparse.FileType('r'))
        parser.add_argument(
            '--account',
            choices=Account.objects.filter(active=True).values_list('slug', flat=True))
        parser.add_argument(
            '--book',
            choices=Book.objects.all().values_list('slug', flat=True))
        parser.add_argument(
            '--user',
            choices=User.objects.all().values_list('username', flat=True))

    def handle(self, *args, **options):
        account = Account.objects.get(slug=options['account'])
        book = Book.objects.get(slug=options['book'])
        user = User.objects.get(username=options['user'])
        csv_file = options['file']
        dry_run = options['dry-run']
        self.stdout.write(
            'Parsing (dry run %s) %s for %s' % (dry_run, csv_file.name, account))
        csv_parser = PARSER_MAPPING[account.parser]
        result = csv_parser().parse(
            csv_file, book=book, user=user, account=account, dry_run=dry_run)
        for error, traceback in result['errors'].items():
            self.stdout.write('=== ERROR: %s ===' % error)
            self.stdout.write('\n'.join(str(i[0]) for i in traceback))
            self.stdout.write('\n\n')
        if dry_run:
            for entry in result['entries']:
                self.stdout.write('=== ENTRY: %s ===' % entry)
