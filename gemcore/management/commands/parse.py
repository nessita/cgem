import argparse

from django.core.management.base import BaseCommand
from gemcore.parse import PARSER_MAPPING


class Command(BaseCommand):

    help = 'Parse a csv files of expense/income entries.'

    def add_arguments(self, parser):
        parser.add_argument('--file', type=argparse.FileType('r'))
        parser.add_argument('--parser', choices=PARSER_MAPPING.keys())

    def handle(self, *args, **options):
        f = options['file']
        expense_parser = PARSER_MAPPING[options['parser']]()
        self.stdout.write(
            'Parsing %s with %s' % (f.name, expense_parser.__class__.__name__))
        result = expense_parser.parse(fileobj=f)
        for error, traceback in result['errors'].items():
            self.stdout.write('=== ERROR ===', error)
            self.stdout.write(traceback)
            self.stdout.write('\n\n')
