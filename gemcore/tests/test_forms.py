from datetime import date

from gemcore.constants import TAGS
from gemcore.forms import EntryForm
from gemcore.tests.helpers import BaseTestCase


class EntryFormTestCase(BaseTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = cls.factory.make_user(username="entry-form-user")
        cls.book = cls.factory.make_book(users=[cls.user])
        cls.account = cls.factory.make_account(users=[cls.user])

    def test_rejects_multiple_submitted_tags(self):
        data = {
            "who": self.user.id,
            "when": date.today().isoformat(),
            "what": "Entry with too many tags",
            "account": self.account.id,
            "amount": "10.00",
            "tags": TAGS[:2],
            "country": "AR",
        }

        with self.assertRaisesMessage(
            ValueError,
            "EntryForm expects exactly one tag.",
        ):
            EntryForm(book=self.book, data=data)

    def test_rejects_instances_with_multiple_tags(self):
        entry = self.factory.make_entry(
            book=self.book,
            account=self.account,
            who=self.user,
            tags=TAGS[:2],
        )

        with self.assertRaisesMessage(
            ValueError,
            "Entry instances must not have multiple tags.",
        ):
            EntryForm(book=self.book, instance=entry)
