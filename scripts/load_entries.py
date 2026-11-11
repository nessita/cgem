import argparse
import csv
import json
import os
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote

import httpx


def read_entries(stream, account, country):
    reader = csv.DictReader(stream)
    required = {"date", "description", "amount", "tag"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("CSV requires date, description, amount, and tag.")
    records = []
    seen = {}
    for row in reader:
        line = reader.line_num
        try:
            when = date.fromisoformat(row["date"]).isoformat()
            what = row["description"].strip()
            tag = row["tag"].strip()
            amount = Decimal(row["amount"])
            if (
                not amount.is_finite()
                or amount.quantize(Decimal(".01")) != amount
            ):
                raise ValueError(
                    "Amount must be finite with at most two decimals."
                )
            if not what or not tag:
                raise ValueError("Description and tag must not be empty.")
        except (
            ValueError,
            TypeError,
            AttributeError,
            InvalidOperation,
        ) as error:
            raise ValueError(f"CSV line {line}: {error}") from error
        identity = when, what, amount
        if identity in seen:
            raise ValueError(
                f"CSV lines {seen[identity]} and {line} are identical; "
                "distinguish their descriptions before loading."
            )
        seen[identity] = line
        records.append(
            {
                "csv_line": line,
                "entry": {
                    "account": account,
                    "when": when,
                    "what": what,
                    "amount": format(abs(amount), ".2f"),
                    "is_income": amount > 0,
                    "tags": [tag],
                    "country": country,
                    "notes": row.get("status", "") or "",
                },
            }
        )
    if not records:
        raise ValueError("CSV contains no transactions.")
    return records


def load_entries(client, url, account, records, batch_size):
    response = client.get(url, params={"account": account, "page_size": 1})
    response.raise_for_status()
    if response.json()["count"] != 0:
        raise ValueError("Target account is not empty; nothing was submitted.")
    created = 0
    for offset in range(0, len(records), batch_size):
        until = offset + batch_size
        batch = records[offset:until]
        response = client.post(url, json=[row["entry"] for row in batch])
        if response.status_code not in {200, 201, 400}:
            response.raise_for_status()
        result = response.json()
        if (
            not isinstance(result, dict)
            or not {"entries", "errors"} <= result.keys()
        ):
            raise ValueError(f"Unexpected bulk API response: {result!r}")
        for error in result["errors"]:
            error["csv_line"] = batch[error["index"]]["csv_line"]
        print(json.dumps(result, ensure_ascii=False), flush=True)
        created += len(result["entries"])
        print(f"Created {created}/{len(records)} entries.", file=sys.stderr)
        if result["errors"]:
            raise ValueError(
                "Import stopped: some rows may have been saved. "
                "See the JSON report for errors and CSV line numbers."
            )
        if len(result["entries"]) != len(batch):
            raise ValueError(
                "Bulk API returned an unexpected number of entries."
            )
    response = client.get(url, params={"account": account, "page_size": 1})
    response.raise_for_status()
    if response.json()["count"] != len(records):
        raise ValueError(
            "Final account entry count differs from the CSV count."
        )
    return created


def main():
    parser = argparse.ArgumentParser(
        description="Load a tagged CSV into a CGEM account via bulk POST."
    )
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("--book", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--country", required=True)
    parser.add_argument(
        "--url", default=os.getenv("CGEM_ROOT_URL", "http://localhost:8000")
    )
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print payloads without API calls",
    )
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive.")
    try:
        with args.csv_file.open(encoding="utf-8-sig", newline="") as stream:
            records = read_entries(stream, args.account, args.country)
        income = sum(
            (
                Decimal(r["entry"]["amount"])
                for r in records
                if r["entry"]["is_income"]
            ),
            Decimal(0),
        )
        expense = sum(
            (
                Decimal(r["entry"]["amount"])
                for r in records
                if not r["entry"]["is_income"]
            ),
            Decimal(0),
        )
        print(
            f"{len(records)} entries; income {income:.2f}; "
            f"expenses {expense:.2f}; net {income - expense:.2f}",
            file=sys.stderr,
        )
        if args.dry_run:
            print(json.dumps(records, ensure_ascii=False, indent=2))
            return
        token = os.getenv("CGEM_TOKEN")
        if not token:
            raise ValueError("Set CGEM_TOKEN before loading entries.")
        url = (
            args.url.rstrip("/") + f"/api/{quote(args.book, safe='')}/entries/"
        )
        with httpx.Client(
            headers={"Authorization": f"Token {token}"}, timeout=60
        ) as client:
            load_entries(client, url, args.account, records, args.batch_size)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        csv.Error,
        httpx.HTTPError,
    ) as error:
        parser.exit(2, f"Error: {error}\n")


if __name__ == "__main__":
    main()
