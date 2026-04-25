from datetime import date, datetime, timedelta
from io import StringIO
from urllib.parse import urlencode

import chardet
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import models
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import (
    require_GET,
    require_http_methods,
    require_POST,
)

from gemcore.constants import ChoicesMixin
from gemcore.forms import (
    AccountBalanceForm,
    AccountTransferForm,
    BookForm,
    ChooseForm,
    CSVExpenseForm,
    CurrencyBalanceForm,
    EntryForm,
    EntryMergeForm,
)
from gemcore.models import Account, Asset, Book, Entry
from gemcore.parser import CSVParser
from gemcore.planning import build_planning_summary

ENTRIES_PER_PAGE = 25
MAX_PAGES = 4


@require_GET
@login_required
def home(request):
    books = request.user.book_set.all()
    if books.count() == 1:
        url = reverse("entries", args=(books.get().slug,))
    else:
        url = reverse("books")
    return HttpResponseRedirect(url)


@require_GET
@login_required
def books(request):
    books = request.user.book_set.all()
    context = dict(books=books)
    return render(request, "gemcore/books.html", context)


@require_http_methods(["GET", "POST"])
@login_required
def book(request, book_slug=None):
    book = None
    if book_slug:
        book = get_object_or_404(Book, slug=book_slug, users=request.user)

    if request.method == "POST":
        form = BookForm(instance=book, data=request.POST)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(reverse(home))
    else:
        form = BookForm(instance=book)
    return render(request, "gemcore/book.html", dict(form=form, book=book))


def parse_request(request, book, **kwargs):
    params = request.GET
    q = params.get("q")
    if q:
        entries = book.by_text(q)
    else:
        entries = book.entry_set.all()

    try:
        when = datetime.strptime(params.get("when"), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        when = None
    else:
        entries = book.entry_set.filter(when=when)

    try:
        year = int(params.get("year"))
    except (ValueError, TypeError):
        year = None
    else:
        entries = entries.filter(when__year=year)

    month = params.get("month")
    if month:
        try:
            month_int = int(datetime.strptime(month, "%b").month)
        except (ValueError, TypeError):
            month_int = None
        else:
            entries = entries.filter(when__month=month_int)

    who = params.get("who")
    if who:
        entries = entries.filter(who__username=who)

    country = params.get("country")
    if country:
        entries = entries.filter(country=country)

    account = params.get("account")
    if account:
        entries = entries.filter(account__slug=account)

    asset = params.get("asset")
    if asset:
        entries = entries.filter(asset__slug=asset)

    currency = params.get("currency")
    if currency:
        entries = entries.filter(account__currency=currency)

    is_income = params.get("is_income")
    if is_income in {"1", "true", "True"}:
        is_income = True
        entries = entries.filter(is_income=True)
    elif is_income in {"0", "false", "False"}:
        is_income = False
        entries = entries.filter(is_income=False)
    else:
        is_income = None

    asset_present = params.get("asset_present")
    if asset_present in {"1", "true", "True"}:
        asset_present = True
        entries = entries.filter(asset__isnull=False)
    elif asset_present in {"0", "false", "False"}:
        asset_present = False
        entries = entries.filter(asset__isnull=True)
    else:
        asset_present = None

    used_tags = list(params.getlist("tag", []))
    if used_tags:
        entries = entries.filter(tags__contains=used_tags)

    any_tags = list(params.getlist("tag_any", []))
    if any_tags:
        tag_query = models.Q()
        for tag in any_tags:
            tag_query |= models.Q(tags__contains=[tag])
        entries = entries.filter(tag_query)

    include_tags = request.GET.getlist("include_tag")
    if include_tags:
        entries = entries.filter(tags__contained_by=include_tags)

    exclude_tags = request.GET.getlist("exclude_tag")
    if exclude_tags:
        entries = entries.exclude(tags__contained_by=exclude_tags)

    investment_related = params.get("investment_related")
    if investment_related in {"1", "true", "True"}:
        investment_related = True
        entries = entries.filter(tags__contains=["INVS"], asset__isnull=False)
    elif investment_related in {"0", "false", "False"}:
        investment_related = False
        entries = entries.exclude(tags__contains=["INVS"], asset__isnull=False)
    else:
        investment_related = None

    start = request.GET.get("start")
    if start:
        try:
            start = datetime.strptime(start, "%Y-%m-%d").date()
        except ValueError:
            start = None
        else:
            entries = entries.filter(when__gte=start)

    end = request.GET.get("end")
    if end:
        try:
            end = datetime.strptime(end, "%Y-%m-%d").date()
        except ValueError:
            end = None
        else:
            entries = entries.filter(when__lte=end)

    if kwargs:
        entries = entries.filter(**kwargs)

    filters = {
        "account": account,
        "asset": asset,
        "country": country,
        "currency": currency,
        "end": end,
        "exclude_tags": exclude_tags,
        "include_tags": include_tags,
        "is_income": is_income,
        "investment_related": investment_related,
        "month": month,
        "asset_present": asset_present,
        "any_tags": any_tags,
        "q": q,
        "qs": urlencode(params),
        "start": start,
        "tags": used_tags,
        "when": when,
        "who": who,
        "year": year,
    }
    available = {
        "assets": book.assets(entries),
        "countries": sorted(book.countries(entries).items()),
        "currencies": sorted(book.currencies(entries).items()),
        "months": [
            (d.strftime("%b").lower(), i)
            for d, i in sorted(book.months(entries).items())
        ],
        "tags": sorted(book.tags(entries).items()),
        "users": sorted(book.who(entries).items()),
        "years": sorted(book.years(entries).items()),
    }
    return entries, filters, available


@require_http_methods(["GET", "POST"])
@login_required
def entries(request, book_slug):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)
    entries, filters, available = parse_request(request, book)
    accounts = Account.objects.by_book(book)
    assets = Asset.objects.by_book(book)

    edit_account_form = ChooseForm(
        queryset=accounts, data=request.POST, prefix="account"
    )
    edit_asset_form = ChooseForm(
        queryset=assets, data=request.POST, prefix="asset"
    )
    edit_tags_form = ChooseForm(
        choices=ChoicesMixin.TAG_CHOICES, data=request.POST, prefix="tags"
    )
    edit_country_form = ChooseForm(
        choices=ChoicesMixin.COUNTRY_CHOICES,
        data=request.POST,
        prefix="country",
    )

    if request.method == "POST":
        here = request.get_full_path()
        error = None

        ids = [int(i) for i in request.POST.getlist("entry")]
        if len(ids) == 0:
            error = "Invalid request, no entries selected."

        entries = entries.filter(id__in=ids)
        if entries.count() != len(ids):
            error = "Invalid request, invalid choices for entries."

        if error:
            if request.htmx:
                msg = messages.Message(messages.ERROR, error)
                return render(request, "_messages.html", {"messages": [msg]})

            messages.error(request, error)
            return HttpResponseRedirect(here)

        if "change-account" in request.POST:
            if edit_account_form.is_valid():
                target = edit_account_form.cleaned_data["target"]
                if not target:
                    messages.error(
                        request, "Invalid request, target account is empty."
                    )
                else:
                    entries.update(account=target)
                    msg = (
                        ", ".join(str(e) for e in entries.order_by("id")),
                        target,
                    )
                    messages.success(
                        request, 'Entries "%s" changed to account %s.' % msg
                    )
            else:
                messages.error(
                    request,
                    "Invalid request for changing the account: %s"
                    % edit_account_form.errors,
                )
            return HttpResponseRedirect(here)

        if "change-asset" in request.POST:
            if edit_asset_form.is_valid():
                target = edit_asset_form.cleaned_data["target"]
                if not target:
                    messages.error(
                        request, "Invalid request, target asset is empty."
                    )
                else:
                    entries.update(asset=target)
                    msg = (
                        ", ".join(str(e) for e in entries.order_by("id")),
                        target,
                    )
                    messages.success(
                        request, 'Entries "%s" changed to asset %s.' % msg
                    )
            else:
                messages.error(
                    request,
                    "Invalid request for changing the asset: %s"
                    % edit_asset_form.errors,
                )
            return HttpResponseRedirect(here)

        if "change-tags" in request.POST:
            if edit_tags_form.is_valid():
                target = edit_tags_form.cleaned_data["target"]
                if not target:
                    messages.error(
                        request, "Invalid request, target tags are empty."
                    )
                else:
                    entries.update(tags=[target])
                    msg = (
                        ", ".join(str(e) for e in entries.order_by("id")),
                        target,
                    )
                    messages.success(
                        request, 'Entries "%s" changed with tags "%s".' % msg
                    )
            else:
                messages.error(
                    request,
                    "Invalid request for changing the tags: %s"
                    % edit_tags_form.errors,
                )
            return HttpResponseRedirect(here)

        if "change-country" in request.POST:
            if edit_country_form.is_valid():
                target = edit_country_form.cleaned_data["target"]
                if not target:
                    messages.error(
                        request, "Invalid request, target country are empty."
                    )
                else:
                    entries.update(country=target)
                    msg = (
                        ", ".join(str(e) for e in entries.order_by("id")),
                        target,
                    )
                    messages.success(
                        request,
                        'Entries "%s" changed with country "%s".' % msg,
                    )
            else:
                messages.error(
                    request,
                    "Invalid request for changing the country: %s"
                    % edit_country_form.errors,
                )
            return HttpResponseRedirect(here)

        context = {"book": book, "entries": entries, "qs": filters["qs"]}
        if "merge-selected" in request.POST:
            template = "gemcore/merge-entries.html"
            when = sorted(set(entries.values_list("when", flat=True)))[-1]
            try:
                merge_dry_run = book.merge_entries(
                    *tuple(entries), dry_run=True, who=request.user, when=when
                )
            except ValueError as e:
                messages.error(request, str(e))
                return HttpResponseRedirect(here)

            context["merge_dry_run"] = merge_dry_run
            context["form"] = EntryMergeForm(initial=dict(when=when))

        elif "remove-selected" in request.POST:
            template = "gemcore/remove-entries.html"

        elif "calculate-balance" in request.POST:
            entries = entries.select_related("account")
            currencies = entries.values_list(
                "account__currency", flat=True
            ).distinct()
            if len(currencies) < 2:
                template = "gemcore/_balance_result.html"
                context["balance"] = book.balance(entries)
            else:
                template = "gemcore/_balance_multiple_currency.html"
                context["balances"] = {
                    currency: book.balance(
                        entries.filter(account__currency=currency)
                    )
                    for currency in currencies
                }

        else:
            raise Http404()

        return render(request, template, context)

    # Process GET.
    entries = entries.order_by("-when", "what", "id")

    try:
        page_size = abs(int(request.GET.get("page_size")))
    except (ValueError, TypeError):
        page_size = ENTRIES_PER_PAGE

    paginator = Paginator(entries, page_size)
    page = request.GET.get("page")
    try:
        entries = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        page = 1
        entries = paginator.page(page)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        page = paginator.num_pages
        entries = paginator.page(paginator.num_pages)
    else:
        page = int(page)

    if paginator.num_pages <= MAX_PAGES:
        start = 1
        end = paginator.num_pages
    else:
        half = MAX_PAGES // 2
        start = page - half
        end = page + half
        if start < 1 and end - start < paginator.num_pages:
            end = end - start + 1
            start = 1
        if end > paginator.num_pages and start > 1:
            start = start - (end - paginator.num_pages)
            end = paginator.num_pages

    when = filters["when"]
    if when:
        when_next = when + timedelta(days=1)
        when_prev = when - timedelta(days=1)
    else:
        when_next = None
        when_prev = None
    currencies = [c for c, i in available["currencies"]]
    context = {
        "book": book,
        "filters": filters,
        "available": available,
        "entries": entries,
        "when_next": when_next,
        "when_prev": when_prev,
        "page_end": end,
        "page_range": range(start, end + 1),
        "page_size": page_size,
        "page_start": start,
        "edit_account_form": edit_account_form,
        "edit_asset_form": edit_asset_form,
        "edit_tags_form": edit_tags_form,
        "edit_country_form": edit_country_form,
        "account_balance_form": AccountBalanceForm(queryset=accounts),
        "currency_balance_form": CurrencyBalanceForm(choices=currencies),
    }
    return render(request, "gemcore/entries.html", context)


@require_http_methods(["GET", "POST"])
@login_required
def entry(request, book_slug, entry_id=None):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)
    entry = None
    if entry_id:
        entry = get_object_or_404(Entry, book=book, id=entry_id)

    context = dict(book=book, entry=entry, qs=urlencode(request.GET))
    if request.method == "POST":
        form = EntryForm(instance=entry, book=book, data=request.POST)
        if form.is_valid():
            entry = form.save()
            if entry is not None:
                # decide where to redirecr next
                kwargs = dict(book_slug=book_slug)
                if "save-and-new" in request.POST:
                    url = reverse("add-entry", kwargs=kwargs)
                elif "save-and-new-same-date" in request.POST:
                    url = reverse("add-entry", kwargs=kwargs)
                    url += "?when=" + entry.when.isoformat()
                elif "save-and-edit" in request.POST:
                    kwargs["entry_id"] = entry.id
                    url = reverse("entry", kwargs=kwargs)
                else:  # could be a remove or 'save-and-go-back'
                    url = (
                        reverse("entries", kwargs=kwargs)
                        + "?"
                        + request.POST["qs"]
                    )
                messages.success(
                    request, 'Entry "%s" successfully processed.' % entry
                )
                return HttpResponseRedirect(url)
    else:
        initial = {}
        if entry is None:
            try:
                last_entry = Entry.objects.filter(
                    who=request.user, book=book
                ).latest("when")
                account = last_entry.account
            except Entry.DoesNotExist:
                account = None

            q = request.GET.get("q", "")
            initial = dict(who=request.user, account=account, what=q)
            when = request.GET.get("when")
            if when:
                initial["when"] = when

        form = EntryForm(instance=entry, book=book, initial=initial)
        if entry:
            try:
                context["entry_prev"] = entry.get_previous_by_when()
            except Entry.DoesNotExist:
                pass
            try:
                context["entry_next"] = entry.get_next_by_when()
            except Entry.DoesNotExist:
                pass

    context["form"] = form
    return render(request, "gemcore/entry.html", context)


@require_http_methods(["GET", "POST"])
@login_required
def entry_remove(request, book_slug, entry_id=None):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)
    entries, filters, available = parse_request(request, book)
    if request.method == "GET":
        entries = entries.filter(id=entry_id)
    elif request.method == "POST":
        entries = entries.filter(id__in=request.POST.getlist("entry"))
    else:
        entries = Entry.objects.none()

    if not entries:
        raise Http404()

    if request.method == "POST":
        if "yes" in request.POST:
            msg = ", ".join(str(e) for e in entries)
            entries.delete()
            messages.success(request, 'Entries "%s" removed.' % msg)
        else:
            messages.warning(request, "Removal of entries cancelled.")
        return HttpResponseRedirect(
            reverse("entries", args=(book.slug,)) + "?" + filters["qs"]
        )

    return render(
        request, "gemcore/remove-entries.html", dict(entries=entries)
    )


@require_POST
@login_required
def entry_merge(request, book_slug):
    assert request.method == "POST"
    book = get_object_or_404(Book, slug=book_slug, users=request.user)
    entries, filters, available = parse_request(
        request, book, id__in=request.POST.getlist("entry")
    )

    if not entries:
        raise Http404()

    url = reverse("entries", args=(book_slug,))
    if "yes" in request.POST:
        form = EntryMergeForm(request.POST)
        if form.is_valid():
            msg = ", ".join(str(e) for e in entries)
            when = form.cleaned_data["when"]
            assert when is not None
            new_entry = book.merge_entries(
                *list(entries), dry_run=False, who=request.user, when=when
            )
            messages.success(request, 'Entries "%s" merged.' % msg)
            url = reverse("entry", args=(book_slug, new_entry.id))
        else:
            messages.warning(
                request, "Merge cancelled, form had errors: %r." % form.errors
            )
    else:
        messages.warning(request, "Merge of entries cancelled.")

    return HttpResponseRedirect(url + "?" + filters["qs"])


@require_http_methods(["GET", "POST"])
@login_required
def load_from_file(request, book_slug):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)

    if request.method == "POST":
        form = CSVExpenseForm(
            book=book, data=request.POST, files=request.FILES
        )
        if form.is_valid():
            uploaded_file = form.cleaned_data.get("csv_file")
            if uploaded_file:
                csv_content = uploaded_file.file.read()
                encoding = chardet.detect(csv_content)["encoding"]
                csv_file = StringIO(csv_content.decode(encoding))
                csv_file.name = uploaded_file.name
            else:
                csv_content = form.cleaned_data.get("csv_content")
                csv_file = StringIO(csv_content)
                csv_file.name = ""

            account = form.cleaned_data["account"]
            if account.parser_config is None:
                messages.error(
                    request,
                    "Parser config for account %s is not set." % account,
                )
                return HttpResponseRedirect(".")

            result = CSVParser(account).parse(
                csv_file, book=book, user=request.user
            )
            success = len(result["entries"])
            errors = len(result["errors"])
            if not errors:
                messages.success(
                    request,
                    "File %s successfully parsed (%s entries added)."
                    % (csv_file.name, success),
                )
            elif success:
                messages.warning(
                    request,
                    "File %s partially parsed (%s successes, %s errors)."
                    % (csv_file.name, success, errors),
                )
            else:
                messages.error(
                    request,
                    "File %s could not be parsed (%s errors)."
                    % (csv_file.name, errors),
                )

            if errors:
                for error in result["errors"]:
                    e = error["exception"]
                    msg = error["message"]
                    data = error["data"]
                    messages.error(request, "%s\n\n%s\n%r" % (e, msg, data))

            return HttpResponseRedirect(
                reverse("entries", kwargs=dict(book_slug=book_slug))
            )
    else:
        form = CSVExpenseForm(book=book)

    context = dict(form=form)
    return render(request, "gemcore/load.html", context)


@require_http_methods(["GET", "POST"])
@login_required
def account_transfer(request, book_slug):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)

    if request.method == "POST":
        form = AccountTransferForm(book, request.POST)
        if form.is_valid():
            source_account = form.cleaned_data.get("source_account")
            source_amount = form.cleaned_data.get("source_amount")
            target_account = form.cleaned_data.get("target_account")
            target_amount = form.cleaned_data.get("target_amount")
            when = form.cleaned_data.get("when")
            what = form.cleaned_data.get("what")
            country = form.cleaned_data.get("country")
            tags = [settings.ENTRY_ACCOUNT_TRANSFER_TAG]

            entries = [
                Entry(
                    book=book,
                    who=request.user,
                    when=when,
                    what=what + " (source)",
                    account=source_account,
                    amount=source_amount,
                    is_income=False,
                    country=country,
                    tags=tags,
                ),
                Entry(
                    book=book,
                    who=request.user,
                    when=when,
                    what=what + " (target)",
                    account=target_account,
                    amount=target_amount,
                    is_income=True,
                    country=country,
                    tags=tags,
                ),
            ]
            for e in entries:
                e.full_clean()

            Entry.objects.bulk_create(entries)

            return HttpResponseRedirect(
                reverse("entries", kwargs=dict(book_slug=book_slug))
            )
    else:
        initial = {}
        when = request.GET.get("when")
        if when:
            initial["when"] = when
        form = AccountTransferForm(book, initial=initial)

    context = dict(form=form)
    return render(request, "gemcore/transfer.html", context)


@require_http_methods(["GET", "POST"])
@login_required
def balance(
    request, book_slug, account_slug=None, currency=None, start=None, end=None
):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)
    accounts = Account.objects.by_book(book)
    currencies = sorted(set(accounts.values_list("currency", flat=True)))

    if request.method == "POST":
        if "get-account-balance" in request.POST:
            form = AccountBalanceForm(queryset=accounts, data=request.POST)
        elif "get-currency-balance" in request.POST:
            form = CurrencyBalanceForm(choices=currencies, data=request.POST)
        else:
            raise Http404()

        if form.is_valid():
            source = form.cleaned_data["source"]
            kwargs = dict(book_slug=book.slug)
            if isinstance(source, Account):
                kwargs["account_slug"] = source.slug
            else:
                kwargs["currency"] = source
            url = reverse("balance", kwargs=kwargs)
            start = form.cleaned_data["start"]
            end = form.cleaned_data["end"]
            qs = {}
            if start:
                qs["start"] = start
            if end:
                qs["end"] = end
            if qs:
                url += "?" + urlencode(qs)
            return HttpResponseRedirect(url)

    chosen_accounts = None
    if account_slug:
        chosen_accounts = accounts.filter(slug=account_slug)
    elif currency:
        chosen_accounts = accounts.filter(currency=currency)

    if chosen_accounts is not None and not chosen_accounts.exists():
        raise Http404

    balance = filters = available = None
    if chosen_accounts:
        entries, filters, available = parse_request(
            request, book, account__in=chosen_accounts
        )
        balance = book.balance(entries)

    account_balance_form = AccountBalanceForm(
        queryset=accounts,
        initial=dict(source=account_slug, start=start, end=end),
    )
    currency_balance_form = CurrencyBalanceForm(
        choices=currencies, initial=dict(source=currency, start=start, end=end)
    )
    context = {
        "balance": balance,
        "book": book,
        "account_slug": account_slug,
        "currency": currency,
        "account_balance_form": account_balance_form,
        "currency_balance_form": currency_balance_form,
        "filters": filters,
        "available": available,
    }
    return render(request, "gemcore/balance.html", context)


@require_GET
@login_required
def planning(request, book_slug, year=None):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)
    entries, filters, available = parse_request(request, book)
    if year is not None:
        start = date(year, 1, 1)
        end = date(year, 12, 31)
        entries = entries.filter(when__gte=start, when__lte=end)
        filters["start"] = start
        filters["end"] = end
        available = {
            "assets": book.assets(entries),
            "countries": sorted(book.countries(entries).items()),
            "currencies": sorted(book.currencies(entries).items()),
            "months": [
                (d.strftime("%b").lower(), i)
                for d, i in sorted(book.months(entries).items())
            ],
            "tags": sorted(book.tags(entries).items()),
            "users": sorted(book.who(entries).items()),
            "years": sorted(book.years(entries).items()),
        }
    planning = build_planning_summary(entries)

    base_params = {
        key: values
        for key, values in request.GET.lists()
        if key not in {"page", "page_size"}
    }
    if year is not None:
        base_params["start"] = [filters["start"].isoformat()]
        base_params["end"] = [filters["end"].isoformat()]

    entries_url = reverse("entries", args=(book.slug,))

    def make_entries_url(currency, **extra_params):
        params = {key: list(values) for key, values in base_params.items()}
        params["currency"] = [currency]
        for key, value in extra_params.items():
            if value is None:
                params.pop(key, None)
            elif isinstance(value, list):
                params[key] = value
            else:
                params[key] = [value]
        return entries_url + "?" + urlencode(params, doseq=True)

    for currency, summary in planning.items():
        summary["links"] = {
            "household_expenses": make_entries_url(
                currency,
                is_income="0",
                exclude_tag="CHNG",
                investment_related="0",
            ),
            "investment_outflows": make_entries_url(
                currency,
                is_income="0",
                tag="INVS",
                investment_related="1",
            ),
            "income_total": make_entries_url(
                currency, is_income="1", exclude_tag="CHNG"
            ),
            "income_salary": make_entries_url(
                currency, is_income="1", tag="WORK"
            ),
            "income_rental": make_entries_url(
                currency, is_income="1", tag="RENT"
            ),
            "income_other_investment": make_entries_url(
                currency, is_income="1", tag="INVS"
            ),
            "income_other": make_entries_url(
                currency,
                is_income="1",
                exclude_tag=["CHNG", "WORK", "RENT", "INVS"],
            ),
            "income_investment_total": make_entries_url(
                currency, is_income="1", tag_any=["RENT", "INVS"]
            ),
            "ignored_change": make_entries_url(
                currency, tag="CHNG"
            ),
        }
        expense_rows_by_tag = []
        for tag in summary["expenses_by_tag"].keys():
            expense_rows_by_tag.append(
                {
                    "tag": tag,
                    "amount": summary["expenses_by_tag"][tag],
                    "url": make_entries_url(
                        currency,
                        tag=tag,
                        is_income="0",
                        investment_related=None,
                    ),
                }
            )
        summary["expenses_by_tag_rows"] = expense_rows_by_tag

        income_rows_by_tag = []
        for tag in summary["income_by_tag"].keys():
            income_rows_by_tag.append(
                {
                    "tag": tag,
                    "amount": summary["income_by_tag"][tag],
                    "url": make_entries_url(
                        currency,
                        tag=tag,
                        is_income="1",
                    ),
                }
            )
        summary["income_by_tag_rows"] = income_rows_by_tag

        investment_outflow_rows_by_tag = []
        for tag in summary["investment_outflows_by_tag"].keys():
            investment_outflow_rows_by_tag.append(
                {
                    "tag": tag,
                    "amount": summary["investment_outflows_by_tag"][tag],
                    "url": make_entries_url(
                        currency,
                        tag=tag,
                        is_income="0",
                        asset_present="1",
                        investment_related=None,
                    ),
                }
            )
        summary["investment_outflows_by_tag_rows"] = (
            investment_outflow_rows_by_tag
        )

        ignored_change_rows_by_tag = []
        for tag in summary["ignored_change_by_tag"].keys():
            ignored_change_rows_by_tag.append(
                {
                    "tag": tag,
                    "amount": summary["ignored_change_by_tag"][tag],
                    "url": make_entries_url(currency, tag=tag),
                }
            )
        summary["ignored_change_by_tag_rows"] = ignored_change_rows_by_tag

        rental_income_rows_by_asset = []
        for (asset_slug, asset_name), amount in summary[
            "rental_income_by_asset"
        ].items():
            rental_income_rows_by_asset.append(
                {
                    "asset_slug": asset_slug,
                    "asset_name": asset_name,
                    "amount": amount,
                    "url": make_entries_url(
                        currency,
                        asset=asset_slug,
                        is_income="1",
                        tag="RENT",
                    ),
                }
            )
        summary["rental_income_by_asset_rows"] = rental_income_rows_by_asset

        other_investment_income_rows_by_asset = []
        for (asset_slug, asset_name), amount in summary[
            "other_investment_income_by_asset"
        ].items():
            other_investment_income_rows_by_asset.append(
                {
                    "asset_slug": asset_slug,
                    "asset_name": asset_name,
                    "amount": amount,
                    "url": make_entries_url(
                        currency,
                        asset=asset_slug,
                        is_income="1",
                        tag="INVS",
                    ),
                }
            )
        summary["other_investment_income_by_asset_rows"] = (
            other_investment_income_rows_by_asset
        )

        investment_outflows_rows_by_asset = []
        for (asset_slug, asset_name), amount in summary[
            "investment_outflows_by_asset"
        ].items():
            investment_outflows_rows_by_asset.append(
                {
                    "asset_slug": asset_slug,
                    "asset_name": asset_name,
                    "amount": amount,
                    "url": make_entries_url(
                        currency,
                        asset=asset_slug,
                        is_income="0",
                        tag="INVS",
                        asset_present="1",
                    ),
                }
            )
        summary["investment_outflows_by_asset_rows"] = (
            investment_outflows_rows_by_asset
        )

    context = {
        "available": available,
        "book": book,
        "filters": filters,
        "planning": planning,
    }
    return render(request, "gemcore/planning.html", context)
