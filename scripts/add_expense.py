import argparse
import os
from pprint import pprint

import requests


def add_expense(
    book, account, what, amount, tags, country, notes, verbose=False
):
    token = os.getenv("CGEM_TOKEN", "Invalid")
    base_url = os.getenv("CGEM_ROOT_URL", "http://localhost:8000")
    endpoint = f"/api/{book}/entries/" if book else "/api/entries/"
    url = base_url.rstrip("/") + endpoint
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Token {token}",
    }
    data = {
        "account": account,
        "what": what,
        "amount": amount,
        "country": country,
        "notes": notes,
    }
    if tags is not None:
        data["tags"] = tags
    if verbose:
        print("\n*** About to POST data to:", url)
        pprint(data)

    response = requests.post(url, json=data, headers=headers, timeout=30)
    if verbose:
        print("\n*** Result:", response.status_code)
    if not response.ok:
        raise SystemExit(f"{response.status_code}: {response.text}")
    pprint(response.json())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument(
        "--book", help="The book slug (otherwise use the default or sole book)"
    )
    parser.add_argument(
        "--account", default="default-account", help="The account slug"
    )
    parser.add_argument(
        "--country",
        default="US",
        help="The country where the expense occurred",
    )
    parser.add_argument(
        "--tags",
        nargs=1,
        help=(
            "One category code or name "
            "(otherwise use account rules or the default)"
        ),
    )
    parser.add_argument(
        "--notes",
        default="Submitted via API",
        help="Extra notes/comments for the expense",
    )
    parser.add_argument("what", help="The expense description")
    parser.add_argument("amount", help="The expense amount")

    args = parser.parse_args()

    add_expense(**vars(args))


if __name__ == "__main__":
    main()
