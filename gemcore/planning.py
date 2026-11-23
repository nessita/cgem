from collections import OrderedDict
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q

from gemcore.checks import tag_configuration_errors

PLANNING_GROUPS = {
    "expenses": "Expenses",
    "investment_outflows": "Investment outflows",
    "income_total": "Total income",
    "income_salary": "Salary income",
    "income_rental": "Rental income",
    "income_other_investment": "Investment inflows",
    "income_other": "Other income",
    "investment_net": "Net investment cash flow",
    "non_salary_net": "Net non-salary cash flow",
    "ignored_change": "Ignored transfer movements",
}


def get_planning_tags():
    errors = tag_configuration_errors()
    if errors:
        raise ImproperlyConfigured(" ".join(errors))
    tags = settings.ENTRY_TAGS.get("planning")
    if tags is None:
        raise ImproperlyConfigured(
            "ENTRY_TAGS['planning'] must map salary, rental, and investment "
            "to category codes."
        )
    return tags.copy()


def planning_group_query(group):
    tags = get_planning_tags()
    salary, rental, investment_tag = (
        tags["salary"],
        tags["rental"],
        tags["investment"],
    )
    change = Q(tags__0=settings.ENTRY_TAGS["transfer"])
    ordinary = ~change
    investment = Q(tags__0=investment_tag)
    income = Q(is_income=True) & ordinary
    return {
        "expenses": Q(is_income=False) & ordinary & ~investment,
        "investment_outflows": Q(is_income=False) & ordinary & investment,
        "income_total": income,
        "income_salary": income & Q(tags__0=salary),
        "income_rental": income & Q(tags__0=rental),
        "income_other_investment": income & Q(tags__0=investment_tag),
        "income_other": income
        & ~Q(tags__0__in=[salary, rental, investment_tag]),
        "investment_net": ordinary & investment,
        "non_salary_net": ordinary
        & (
            (Q(is_income=True) & ~Q(tags__0=salary))
            | Q(is_income=False, tags__0=investment_tag)
        ),
        "ignored_change": change,
    }[group]


def _classify_income(entry, tags):
    tag = entry.tags[0]
    if tag == tags["salary"]:
        return "salary"

    if tag == tags["rental"]:
        return "rental"

    if tag == tags["investment"]:
        return "other_investment"

    return "other"


def _is_investment_outflow(entry, tags):
    return not entry.is_income and entry.tags[0] == tags["investment"]


def _empty_cash_flow():
    return {
        "expenses": {"amount": Decimal("0")},
        "investment_outflows": {"amount": Decimal("0")},
        "income_total": {"amount": Decimal("0")},
        "income_salary": {"amount": Decimal("0")},
        "income_rental": {"amount": Decimal("0")},
        "income_other_investment": {"amount": Decimal("0")},
        "income_other": {"amount": Decimal("0")},
        "ignored_change": {"amount": Decimal("0")},
        "entries_count": 0,
    }


def _empty_currency_summary():
    return {
        **_empty_cash_flow(),
        "months": OrderedDict(),
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
    metric["count"] = metric.get("count", 0) + 1


def _add_tag_breakdown(summary, key, entry):
    tag = entry.tags[0]
    summary[key][tag] = summary[key].get(tag, Decimal("0")) + entry.amount


def _add_asset_breakdown(summary, key, entry):
    if entry.asset is None:
        return

    asset_key = (entry.asset.slug, entry.asset.name)
    summary[key][asset_key] = (
        summary[key].get(asset_key, Decimal("0")) + entry.amount
    )


def _finish_cash_flow(summary):
    income = summary["income_total"]["amount"]
    salary = summary["income_salary"]["amount"]
    investment_outflows = summary["investment_outflows"]["amount"]
    expenses = summary["expenses"]["amount"]
    summary["investment_net"] = {
        "amount": (
            summary["income_other_investment"]["amount"] - investment_outflows
        ),
    }
    summary["non_salary_net"] = {
        "amount": income - salary - investment_outflows,
    }
    summary["net_result"] = {
        "amount": income - investment_outflows - expenses,
    }
    summary["coverage_gap"] = {
        "amount": summary["non_salary_net"]["amount"] - expenses,
    }
    summary["coverage_percent"] = (
        summary["non_salary_net"]["amount"] / expenses * 100
        if expenses > 0
        else None
    )


def build_planning_summary(entries):
    tags = get_planning_tags()
    result = OrderedDict()

    for entry in entries.select_related("account", "asset").order_by(
        "account__currency", "when", "id"
    ):
        currency = entry.account.currency
        if currency not in result:
            result[currency] = _empty_currency_summary()
        summary = result[currency]
        month_start = entry.when.replace(day=1)
        if month_start not in summary["months"]:
            summary["months"][month_start] = {
                "when": month_start,
                **_empty_cash_flow(),
            }
        month = summary["months"][month_start]
        if entry.tags[0] == settings.ENTRY_TAGS["transfer"]:
            group = "ignored_change"
        elif _is_investment_outflow(entry, tags):
            group = "investment_outflows"
        elif entry.is_income:
            group = "income_" + _classify_income(entry, tags)
        else:
            group = "expenses"

        for totals in (summary, month):
            totals["entries_count"] += 1
            _add_metric(totals[group], entry)
            if entry.is_income and group != "ignored_change":
                _add_metric(totals["income_total"], entry)

        if group == "ignored_change":
            _add_tag_breakdown(summary, "ignored_change_by_tag", entry)
            continue

        if group == "investment_outflows":
            _add_tag_breakdown(summary, "investment_outflows_by_tag", entry)
            _add_asset_breakdown(
                summary, "investment_outflows_by_asset", entry
            )
            continue

        if entry.is_income:
            _add_tag_breakdown(summary, "income_by_tag", entry)
            if group == "income_rental":
                _add_asset_breakdown(summary, "rental_income_by_asset", entry)
            elif group == "income_other_investment":
                _add_asset_breakdown(
                    summary, "other_investment_income_by_asset", entry
                )
        else:
            _add_tag_breakdown(summary, "expenses_by_tag", entry)

    for summary in result.values():
        _finish_cash_flow(summary)
        cumulative_gap = Decimal("0")
        for month in summary["months"].values():
            _finish_cash_flow(month)
            cumulative_gap += month["coverage_gap"]["amount"]
            month["cumulative_gap"] = cumulative_gap

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
