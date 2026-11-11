import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict, deque
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote

import httpx


def amount(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"Invalid amount {value!r}.") from None
    if not result.is_finite():
        raise ValueError("Amounts must be finite numbers.")
    return result


def read_csv(stream):
    reader = csv.DictReader(stream)
    required = {"date", "description", "amount"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("CSV requires date, description, and amount columns.")
    entries = []
    for row in reader:
        if any(row[name] is None for name in required):
            raise ValueError(f"CSV line {reader.line_num} has missing values.")
        entries.append(
            {
                "date": date.fromisoformat(row["date"]).isoformat(),
                "description": row["description"].strip(),
                "amount": amount(row["amount"]),
                "line": reader.line_num,
                "status": row.get("status", ""),
                "tag": row.get("tag", ""),
            }
        )
    if not entries:
        raise ValueError("The CSV has no transactions.")
    return entries


def fetch_entries(base_url, book, account, start, end):
    token = os.getenv("CGEM_TOKEN")
    if not token:
        raise ValueError("Set CGEM_TOKEN or provide --api-json.")
    endpoint = (
        f"/api/{quote(book, safe='')}/entries/" if book else "/api/entries/"
    )
    url = base_url.rstrip("/") + endpoint
    params = {
        "account": account,
        "start": start,
        "end": end,
        "page_size": 100,
        "page": 1,
    }
    entries = []
    count = None
    with httpx.Client(
        headers={"Authorization": f"Token {token}"}, timeout=30
    ) as client:
        while True:
            response = client.get(url, params=params)
            response.raise_for_status()
            page = response.json()
            if count is None:
                count = page["count"]
            if page["count"] != count:
                raise ValueError("API count changed during pagination; retry.")
            entries.extend(page["results"])
            if page["next"] is None:
                break
            if not page["results"] or len(entries) >= count:
                raise ValueError("API pagination is inconsistent.")
            # Proxy-generated pagination must not change the token recipient.
            params["page"] += 1
    if len(entries) != count:
        raise ValueError("The API did not return its advertised entry count.")
    return entries


def read_json(stream):
    data = json.load(stream)
    if isinstance(data, dict):
        if data.get("next") is not None or data["count"] != len(
            data["results"]
        ):
            raise ValueError(
                "Saved API JSON is incomplete; include every page."
            )
        data = data["results"]
    if not isinstance(data, list):
        raise ValueError("API JSON must be an entry array or a complete page.")
    return data


def normalize_api(entries, account, start, end, book=None):
    result = []
    seen = set()
    books = set()
    for entry in entries:
        if entry["account"] != account:
            continue
        if book is not None and entry["book"] != book:
            continue
        when = date.fromisoformat(entry["when"]).isoformat()
        if not start <= when <= end:
            continue
        books.add(entry["book"])
        if len(books) > 1:
            raise ValueError("Entries span multiple books; provide --book.")
        if entry["id"] in seen:
            raise ValueError(f"Repeated API entry ID {entry['id']}.")
        seen.add(entry["id"])
        if not isinstance(entry["is_income"], bool):
            raise ValueError("API is_income must be a JSON boolean.")
        value = amount(entry["amount"])
        if value < 0:
            raise ValueError("API amounts must be nonnegative.")
        result.append(
            {
                "date": when,
                "description": entry["what"].strip(),
                "amount": value if entry["is_income"] else -value,
                "id": entry["id"],
                "tags": entry["tags"],
                "notes": entry.get("notes", ""),
            }
        )
    return result


def reconcile(csv_entries, api_entries):
    def key(entry):
        return entry["date"], entry["description"], entry["amount"]

    available = defaultdict(deque)
    for entry in api_entries:
        available[key(entry)].append(entry)
    for entry in csv_entries:
        matches = available[key(entry)]
        if matches:
            yield "MATCH", entry, matches.popleft()
        else:
            yield "CSV_ONLY", entry, None
    for entries in available.values():
        for entry in entries:
            yield "CGEM_ONLY", None, entry


def write_report(stream, comparisons):
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(
        (
            "result",
            "csv_line",
            "cgem_id",
            "date",
            "description",
            "signed_amount",
            "csv_status",
            "csv_tag",
            "cgem_tags",
            "cgem_notes",
        )
    )
    counts = Counter()
    for status, left, right in comparisons:
        entry = left if left is not None else right
        writer.writerow(
            (
                status,
                left["line"] if left else "",
                right["id"] if right else "",
                entry["date"],
                entry["description"],
                format(entry["amount"], ".2f"),
                left["status"] if left else "",
                left["tag"] if left else "",
                ";".join(right["tags"]) if right else "",
                right["notes"] if right else "",
            )
        )
        counts[status] += 1
    return counts


def print_totals(label, entries):
    income = sum((e["amount"] for e in entries if e["amount"] > 0), Decimal(0))
    expense = -sum(
        (e["amount"] for e in entries if e["amount"] < 0), Decimal(0)
    )
    print(
        f"{label}: {len(entries)} entries; income {income:.2f}; "
        f"expenses {expense:.2f}; net {income - expense:.2f}",
        file=sys.stderr,
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile a CSV by date, description, and signed amount. "
            "Duplicates are matched individually; outer whitespace is "
            "stripped from descriptions. CSV output includes every match and "
            "difference. Exit codes: 0 matches, 1 differences, 2 error."
        )
    )
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("--account", required=True)
    parser.add_argument(
        "--book", help="Otherwise use the default or sole book"
    )
    parser.add_argument(
        "--url", default=os.getenv("CGEM_ROOT_URL", "http://localhost:8000")
    )
    parser.add_argument(
        "--api-json", type=Path, help="Use a saved complete export"
    )
    args = parser.parse_args()
    try:
        with args.csv_file.open(encoding="utf-8-sig", newline="") as stream:
            csv_entries = read_csv(stream)
        start = min(entry["date"] for entry in csv_entries)
        end = max(entry["date"] for entry in csv_entries)
        if args.api_json:
            with args.api_json.open(encoding="utf-8-sig") as stream:
                entries = read_json(stream)
        else:
            entries = fetch_entries(
                args.url, args.book, args.account, start, end
            )
        api_entries = normalize_api(
            entries, args.account, start, end, args.book
        )
        print(
            f"Account {args.account}; period {start} to {end}", file=sys.stderr
        )
        print_totals("CSV", csv_entries)
        print_totals("CGEM", api_entries)
        counts = write_report(sys.stdout, reconcile(csv_entries, api_entries))
        print(
            f"Matched: {counts['MATCH']}; CSV only: {counts['CSV_ONLY']}; "
            f"CGEM only: {counts['CGEM_ONLY']}",
            file=sys.stderr,
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        csv.Error,
        httpx.HTTPError,
    ) as error:
        parser.exit(2, f"Error: {error}\n")
    return int(bool(counts["CSV_ONLY"] or counts["CGEM_ONLY"]))


if __name__ == "__main__":
    sys.exit(main())
