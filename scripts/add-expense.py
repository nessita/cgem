import argparse
import os
import requests
from pprint import pprint


def add_expense(
    book, account, what, amount, tags, country, notes, verbose=False
):
    token = os.getenv('CGEM_TOKEN', 'Invalid')
    base_url = os.getenv('CGEM_ROOT_URL', 'http://localhost:8000')
    endpoint = '/api/entries/'
    url = base_url + endpoint
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Token {token}',
    }
    data = {
        'book': book,
        'account': account,
        'what': what,
        'amount': amount,
        'tags': tags,
        'country': country,
        'notes': notes,
    }
    if verbose:
        print('\n*** About to POST data to:', url)
        print('*** with headers:', headers)
        pprint(data)

    response = requests.post(url, json=data, headers=headers)
    if verbose:
        print('\n*** Result:', response.status_code)
    assert response.ok, '%s: %s' % (response.status_code, response.text)
    pprint(response.json())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument('--book', default='default-book', help='The book slug')
    parser.add_argument(
        '--account', default='default-account', help='The account slug'
    )
    parser.add_argument(
        '--country',
        default='US',
        help='The country where the expense occurred',
    )
    parser.add_argument('--tags', nargs='+', default=['imported'])
    parser.add_argument(
        '--notes',
        default='Submitted via API',
        help='Extra notes/comments for the expense',
    )
    parser.add_argument('what', help='The expense description')
    parser.add_argument('amount', help='The expense amount')

    args = parser.parse_args()

    add_expense(**vars(args))


if __name__ == '__main__':
    main()
