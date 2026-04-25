from collections import OrderedDict
from decimal import Decimal

from django.conf import settings


CHANGE_TAG = settings.ENTRY_ACCOUNT_TRANSFER_TAG
INVESTMENT_TAG = "INVS"
RENT_TAG = "RENT"
WORK_TAG = "WORK"


def _entry_tag(entry):
    if not entry.tags:
        return None
    return entry.tags[0]


def _classify_income(entry):
    tag = _entry_tag(entry)
    if tag == WORK_TAG:
        return "salary"

    if tag == RENT_TAG:
        return "rental"

    if tag == INVESTMENT_TAG:
        return "other_investment"

    return "other"


def _is_investment_outflow(entry):
    return (
        not entry.is_income
        and entry.asset is not None
        and _entry_tag(entry) == INVESTMENT_TAG
    )


def _empty_currency_summary():
    return {
        "expenses": {"amount": Decimal("0"), "tags": set()},
        "investment_outflows": {"amount": Decimal("0"), "tags": set()},
        "income_total": {"amount": Decimal("0"), "tags": set()},
        "income_salary": {"amount": Decimal("0"), "tags": set()},
        "income_rental": {"amount": Decimal("0"), "tags": set()},
        "income_other_investment": {
            "amount": Decimal("0"),
            "tags": set(),
        },
        "income_other": {"amount": Decimal("0"), "tags": set()},
        "ignored_change": {"amount": Decimal("0"), "tags": set()},
        "entries_count": 0,
        "expenses_by_tag": OrderedDict(),
        "income_by_tag": OrderedDict(),
        "investment_outflows_by_tag": OrderedDict(),
        "ignored_change_by_tag": OrderedDict(),
        "rental_income_by_asset": OrderedDict(),
        "other_investment_income_by_asset": OrderedDict(),
        "investment_outflows_by_asset": OrderedDict(),
    }


def _add_metric(metric, entry):
    metric["amount"] += entry.amount
    tag = _entry_tag(entry)
    if tag is not None:
        metric["tags"].add(tag)


def _add_tag_breakdown(summary, key, entry):
    tag = _entry_tag(entry) or "UNTAGGED"
    summary[key][tag] = summary[key].get(tag, Decimal("0")) + entry.amount


def _add_asset_breakdown(summary, key, entry):
    if entry.asset is None:
        return

    asset_key = (entry.asset.slug, entry.asset.name)
    summary[key][asset_key] = (
        summary[key].get(asset_key, Decimal("0")) + entry.amount
    )


def build_planning_summary(entries):
    result = OrderedDict()

    for entry in entries.select_related("account", "asset").order_by(
        "account__currency", "when", "id"
    ):
        currency = entry.account.currency
        summary = result.setdefault(currency, _empty_currency_summary())
        summary["entries_count"] += 1

        if _entry_tag(entry) == CHANGE_TAG:
            _add_metric(summary["ignored_change"], entry)
            _add_tag_breakdown(summary, "ignored_change_by_tag", entry)
            continue

        if _is_investment_outflow(entry):
            _add_metric(summary["investment_outflows"], entry)
            _add_tag_breakdown(summary, "investment_outflows_by_tag", entry)
            _add_asset_breakdown(summary, "investment_outflows_by_asset", entry)
            continue

        if entry.is_income:
            _add_metric(summary["income_total"], entry)
            _add_tag_breakdown(summary, "income_by_tag", entry)
            classification = _classify_income(entry)
            if classification == "salary":
                _add_metric(summary["income_salary"], entry)
            elif classification == "rental":
                _add_metric(summary["income_rental"], entry)
                _add_asset_breakdown(summary, "rental_income_by_asset", entry)
            elif classification == "other_investment":
                _add_metric(summary["income_other_investment"], entry)
                _add_asset_breakdown(
                    summary, "other_investment_income_by_asset", entry
                )
            else:
                _add_metric(summary["income_other"], entry)
        else:
            _add_metric(summary["expenses"], entry)
            _add_tag_breakdown(summary, "expenses_by_tag", entry)

    for summary in result.values():
        summary["income_investment_total"] = {
            "amount": (
                summary["income_rental"]["amount"]
                + summary["income_other_investment"]["amount"]
            ),
            "tags": (
                summary["income_rental"]["tags"]
                | summary["income_other_investment"]["tags"]
            ),
        }
        summary["household_expenses"] = {
            "amount": summary["expenses"]["amount"],
            "tags": set(summary["expenses"]["tags"]),
        }
        summary["net_result"] = {
            "amount": (
                summary["income_total"]["amount"]
                - summary["expenses"]["amount"]
            ),
            "tags": (
                summary["income_total"]["tags"] | summary["expenses"]["tags"]
            ),
        }
        summary["investment_coverage_gap"] = {
            "amount": (
                summary["income_investment_total"]["amount"]
                - summary["expenses"]["amount"]
            ),
            "tags": (
                summary["income_investment_total"]["tags"]
                | summary["expenses"]["tags"]
            ),
        }
        summary["sustainability"] = {
            "household_expenses": {
                "amount": summary["expenses"]["amount"],
                "tags": set(summary["expenses"]["tags"]),
            },
            "salary_income": {
                "amount": summary["income_salary"]["amount"],
                "tags": set(summary["income_salary"]["tags"]),
            },
            "rental_income": {
                "amount": summary["income_rental"]["amount"],
                "tags": set(summary["income_rental"]["tags"]),
            },
            "other_investment_income": {
                "amount": summary["income_other_investment"]["amount"],
                "tags": set(summary["income_other_investment"]["tags"]),
            },
            "investment_income_total": {
                "amount": summary["income_investment_total"]["amount"],
                "tags": set(summary["income_investment_total"]["tags"]),
            },
            "investment_minus_household_expenses": {
                "amount": summary["investment_coverage_gap"]["amount"],
                "tags": (
                    summary["income_investment_total"]["tags"]
                    | summary["expenses"]["tags"]
                ),
            },
            "total_income_minus_household_expenses": {
                "amount": (
                    summary["income_total"]["amount"]
                    - summary["expenses"]["amount"]
                ),
                "tags": (
                    summary["income_total"]["tags"]
                    | summary["expenses"]["tags"]
                ),
            },
        }

        for key, value in summary.items():
            if isinstance(value, dict) and "tags" in value:
                value["tags"] = sorted(value["tags"])
            elif key == "sustainability":
                for nested_value in value.values():
                    nested_value["tags"] = sorted(nested_value["tags"])

        for key in (
            "expenses_by_tag",
            "income_by_tag",
            "investment_outflows_by_tag",
            "ignored_change_by_tag",
        ):
            summary[key] = OrderedDict(sorted(summary[key].items()))

        for key in (
            "rental_income_by_asset",
            "other_investment_income_by_asset",
            "investment_outflows_by_asset",
        ):
            summary[key] = OrderedDict(
                sorted(summary[key].items(), key=lambda item: item[0][1])
            )

    return result
