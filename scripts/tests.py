import csv
import json
import os
import runpy
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock

import httpx

BASE_DIR = Path(__file__).resolve().parent


class AddExpenseTestCase(TestCase):
    def run_script(self, arguments, post):
        script = BASE_DIR / "add_expense.py"
        output = StringIO()
        with (
            mock.patch.dict(
                os.environ,
                CGEM_TOKEN="example-secret-token",
                CGEM_ROOT_URL="http://testserver/",
            ),
            mock.patch.dict(
                "sys.modules", requests=SimpleNamespace(post=post)
            ),
            mock.patch("sys.argv", [str(script), *arguments]),
            redirect_stdout(output),
            redirect_stderr(StringIO()),
        ):
            runpy.run_path(str(script), run_name="__main__")
        return output.getvalue()

    def test_add_expense_script_respects_selected_book(self):
        for book, endpoint in (
            (None, "/api/entries/"),
            ("family", "/api/family/entries/"),
        ):
            post = mock.Mock(
                return_value=SimpleNamespace(
                    ok=True, status_code=201, json=lambda: {"id": 42}
                )
            )
            arguments = [
                "--account",
                "cash",
                "--country",
                "AR",
                "--notes",
                "From the CLI",
                "Lunch",
                "12.50",
            ]
            if book:
                arguments.extend(["--book", book])
            with self.subTest(book=book):
                output = self.run_script(arguments, post)
                post.assert_called_once_with(
                    "http://testserver" + endpoint,
                    json={
                        "account": "cash",
                        "what": "Lunch",
                        "amount": "12.50",
                        "country": "AR",
                        "notes": "From the CLI",
                    },
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": "Token example-secret-token",
                    },
                    timeout=30,
                )
                self.assertIn("42", output)

    def test_explicit_category_is_submitted_without_logging_token(self):
        post = mock.Mock(
            return_value=SimpleNamespace(
                ok=True, status_code=201, json=lambda: {"id": 42}
            )
        )
        output = self.run_script(
            ["--verbose", "--tags", "food", "Lunch", "12.50"], post
        )
        self.assertEqual(post.call_args.kwargs["json"]["tags"], ["food"])
        self.assertIn("About to POST", output)
        self.assertIn("Result: 201", output)
        self.assertNotIn("example-secret-token", output)
        self.assertNotIn("Authorization", output)

    def test_multiple_categories_are_rejected_before_posting(self):
        post = mock.Mock()
        with self.assertRaisesRegex(SystemExit, "^2$"):
            self.run_script(
                ["--tags", "food", "travel", "Lunch", "12.50"], post
            )
        post.assert_not_called()

    def test_unsuccessful_response_fails(self):
        post = mock.Mock(
            return_value=SimpleNamespace(
                ok=False, status_code=400, text="Invalid entry."
            )
        )
        with self.assertRaisesRegex(SystemExit, r"400: Invalid entry\."):
            self.run_script(["Lunch", "12.50"], post)
        post.assert_called_once()


class LoadEntriesTestCase(TestCase):
    def setUp(self):
        self.script = runpy.run_path(str(BASE_DIR / "load_entries.py"))
        self.records = self.script["read_entries"](
            StringIO(
                "date,description,amount,tag,status\n"
                "2026-11-01,Lunch,-10.00,food,\n"
                "2026-11-02,Transfer,30.00,change,\n"
                "2026-11-03,Coffee,-5.00,food,\n"
            ),
            "new-account",
            "AR",
        )

    def test_csv_amounts_tags_and_duplicate_validation(self):
        records = self.script["read_entries"](
            StringIO(
                "date,description,amount,tag,status\n"
                "2026-11-01,Paperwork,-12.50,bureaucracy,En curso\n"
            ),
            "new-account",
            "AR",
        )
        self.assertEqual(records[0]["csv_line"], 2)
        self.assertEqual(records[0]["entry"]["tags"], ["bureaucracy"])
        self.assertEqual(records[0]["entry"]["amount"], "12.50")
        self.assertIs(records[0]["entry"]["is_income"], False)
        self.assertIs(self.records[1]["entry"]["is_income"], True)
        self.assertEqual(records[0]["entry"]["notes"], "En curso")
        with self.assertRaisesRegex(ValueError, "CSV lines 2 and 3"):
            self.script["read_entries"](
                StringIO(
                    "date,description,amount,tag\n"
                    "2026-11-01,Coffee,-10.00,food\n"
                    "2026-11-01,Coffee,-10.00,food\n"
                ),
                "new-account",
                "AR",
            )

    def test_loads_all_batches_and_checks_final_count(self):
        calls = []
        created = []

        def respond(request):
            calls.append(request.method)
            if request.method == "GET":
                self.assertEqual(request.url.params["account"], "new-account")
                return httpx.Response(200, json={"count": len(created)})
            batch = json.loads(request.content)
            first_id = len(created) + 1
            created.extend(batch)
            return httpx.Response(
                201,
                json={
                    "entries": [
                        {"id": i} for i in range(first_id, len(created) + 1)
                    ],
                    "errors": [],
                },
            )

        with (
            httpx.Client(transport=httpx.MockTransport(respond)) as client,
            redirect_stdout(StringIO()),
            redirect_stderr(StringIO()),
        ):
            count = self.script["load_entries"](
                client,
                "http://testserver/api/family/entries/",
                "new-account",
                self.records,
                2,
            )
        self.assertEqual(count, 3)
        self.assertEqual(created, [row["entry"] for row in self.records])
        self.assertEqual(calls, ["GET", "POST", "POST", "GET"])

    def test_nonempty_account_is_rejected_before_posting(self):
        methods = []

        def respond(request):
            methods.append(request.method)
            return httpx.Response(200, json={"count": 1})

        with (
            httpx.Client(transport=httpx.MockTransport(respond)) as client,
            self.assertRaisesRegex(ValueError, "not empty"),
        ):
            self.script["load_entries"](
                client,
                "http://testserver/api/family/entries/",
                "new-account",
                self.records,
                2,
            )
        self.assertEqual(methods, ["GET"])

    def test_partial_failure_reports_source_line_and_stops(self):
        methods = []

        def respond(request):
            methods.append(request.method)
            if request.method == "GET":
                return httpx.Response(200, json={"count": 0})
            return httpx.Response(
                200,
                json={
                    "entries": [{"id": 1}],
                    "errors": [
                        {"index": 1, "errors": {"tags": ["Invalid tag"]}}
                    ],
                },
            )

        output = StringIO()
        with (
            httpx.Client(transport=httpx.MockTransport(respond)) as client,
            redirect_stdout(output),
            redirect_stderr(StringIO()),
            self.assertRaisesRegex(
                ValueError, "some rows may have been saved"
            ),
        ):
            self.script["load_entries"](
                client,
                "http://testserver/api/family/entries/",
                "new-account",
                self.records,
                2,
            )
        self.assertEqual(methods, ["GET", "POST"])
        self.assertEqual(
            json.loads(output.getvalue())["errors"][0]["csv_line"], 3
        )


class ReconcileEntriesTestCase(TestCase):

    def test_reconcile_script_matches_duplicate_occurrences_individually(self):
        script = runpy.run_path(str(BASE_DIR / "reconcile_entries.py"))
        source = StringIO(
            "date,description,amount,status\n"
            "2026-11-06, Coffee ,-10.00,\n"
            "2026-11-06,Coffee,-10.00,En curso\n"
            "2026-11-06,Salary,100.00,\n"
        )
        csv_entries = script["read_csv"](source)
        common = {
            "account": "prex",
            "book": "family",
            "when": "2026-11-06",
            "what": "Coffee",
            "amount": "10.00",
            "is_income": False,
            "tags": ["FOOD"],
        }
        api_entries = script["normalize_api"](
            [
                {**common, "id": 1},
                {
                    **common,
                    "id": 2,
                    "what": "Salary",
                    "amount": "100",
                    "is_income": True,
                },
                {**common, "id": 3, "what": "CGEM only", "amount": "7"},
                {**common, "id": 4, "when": "2026-12-01"},
                {**common, "id": 5, "account": "another"},
                {**common, "id": 6, "book": "another"},
            ],
            "prex",
            "2026-11-06",
            "2026-11-06",
            "family",
        )
        comparisons = list(script["reconcile"](csv_entries, api_entries))
        self.assertEqual(
            [
                (
                    status,
                    left["line"] if left else None,
                    right["id"] if right else None,
                )
                for status, left, right in comparisons
            ],
            [
                ("MATCH", 2, 1),
                ("CSV_ONLY", 3, None),
                ("MATCH", 4, 2),
                ("CGEM_ONLY", None, 3),
            ],
        )
        output = StringIO()
        counts = script["write_report"](output, comparisons)
        self.assertEqual(counts, {"MATCH": 2, "CSV_ONLY": 1, "CGEM_ONLY": 1})
        report = list(csv.DictReader(StringIO(output.getvalue())))
        self.assertEqual(report[0]["signed_amount"], "-10.00")
        self.assertEqual(report[1]["csv_status"], "En curso")
        self.assertEqual(report[-1]["signed_amount"], "-7.00")
        extra = {**api_entries[0], "id": 7}
        comparisons = list(
            script["reconcile"](csv_entries[:1], [api_entries[0], extra])
        )
        self.assertEqual(
            [status for status, _, _ in comparisons], ["MATCH", "CGEM_ONLY"]
        )
        self.assertEqual(comparisons[-1][2]["id"], 7)
        with self.assertRaisesRegex(ValueError, "incomplete"):
            script["read_json"](
                StringIO(json.dumps({"count": 2, "results": [], "next": None}))
            )

    def test_reconcile_script_fetches_every_page_from_selected_endpoint(self):
        script = runpy.run_path(str(BASE_DIR / "reconcile_entries.py"))
        pages = []

        def respond(request):
            self.assertEqual(request.url.host, "testserver")
            self.assertEqual(request.url.path, "/api/family/entries/")
            self.assertEqual(request.headers["Authorization"], "Token example")
            self.assertEqual(request.url.params["account"], "prex")
            self.assertEqual(request.url.params["start"], "2026-11-01")
            self.assertEqual(request.url.params["end"], "2026-11-06")
            page = int(request.url.params["page"])
            pages.append(page)
            return httpx.Response(
                200,
                json={
                    "count": 2,
                    "results": [{"id": page}],
                    "next": (
                        "https://other.example/api/?page=2"
                        if page == 1
                        else None
                    ),
                },
            )

        client_class = httpx.Client
        with (
            mock.patch.dict(os.environ, CGEM_TOKEN="example"),
            mock.patch(
                "httpx.Client",
                side_effect=lambda **kwargs: client_class(
                    transport=httpx.MockTransport(respond), **kwargs
                ),
            ),
        ):
            entries = script["fetch_entries"](
                "http://testserver",
                "family",
                "prex",
                "2026-11-01",
                "2026-11-06",
            )
        self.assertEqual(entries, [{"id": 1}, {"id": 2}])
        self.assertEqual(pages, [1, 2])
