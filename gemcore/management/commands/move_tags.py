import operator
from functools import reduce

from django.core.management.base import BaseCommand, CommandError

from gemcore.models import Entry


class Command(BaseCommand):

    def handle(self, *args, **options):
        for entry in Entry.objects.all():
            tags = list(entry.tags.names())
            if not tags:
                self.stderr.write(
                    '=== ERROR: entry %s %s has no tags.\n' %
                    (entry.id, entry))
                continue

            # remove country
            country = [s for s in tags if s in ('AR', 'UY')]
            assert len(country) == 1
            country = country[0]

            self.stdout.write(
                'Processing entry %s %s country %s tags %s\n' %
                (entry.id, entry, country, tags))

            tags.remove(country)
            entry.country = country

            entry.flags = reduce(
                operator.or_, [getattr(Entry.flags, t.lower()) for t in tags])
            entry.save()
