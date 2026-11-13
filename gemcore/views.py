from datetime import date, datetime, timedelta
from io import StringIO

import chardet
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import BadRequest, ImproperlyConfigured
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import (
    Http404,
    HttpResponseBadRequest,
    HttpResponseRedirect,
    QueryDict,
)
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import (
    require_GET,
    require_http_methods,
    require_POST,
)
from django.views.decorators.vary import vary_on_headers

from gemcore.constants import ChoicesMixin
from gemcore.forms import (
    AccountBalanceForm,
    AccountTransferForm,
    BookForm,
    ChooseForm,
    CSVExpenseForm,
    CurrencyBalanceForm,
    EntryFilterForm,
    EntryForm,
    EntryMergeForm,
)
from gemcore.models import Account, Asset, Book, Entry
from gemcore.parser import CSVParser
from gemcore.planning import (
    PLANNING_GROUPS,
    build_planning_summary,
    get_planning_tags,
    planning_group_query,
)

ENTRIES_PER_PAGE = 25
MAX_PAGES = 4
ENTRY_ORDERING = ("-when", "what", "id")
COUNTRY_BY_CURRENCY = {
    "ARS": "AR",
    "BRL": "BR",
    "CAD": "CA",
    "CNY": "CN",
    "EUR": "",
    "GBP": "GB",
    "USD": "US",
    "UYU": "UY",
}


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
    filter_form = EntryFilterForm(params)
    if not filter_form.is_valid():
        raise BadRequest(filter_form.errors.as_text())
    q = params.get("q")
    if q:
        entries = book.by_text(q)
    else:
        entries = book.entry_set.all()

    when = filter_form.cleaned_data["when"]
    if when:
        entries = entries.filter(when=when)

    year = filter_form.cleaned_data["year"]
    if year:
        entries = entries.filter(when__year=year)

    month = filter_form.cleaned_data["month"]
    if month:
        month_int = datetime.strptime(month, "%b").month
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

    is_income = filter_form.cleaned_data["is_income"]
    if is_income is not None:
        entries = entries.filter(is_income=is_income)

    asset_present = filter_form.cleaned_data["asset_present"]
    if asset_present is not None:
        entries = entries.filter(asset__isnull=not asset_present)

    used_tags = list(params.getlist("tag", []))
    if used_tags:
        entries = entries.filter(tags__contains=used_tags)

    any_tags = list(params.getlist("tag_any", []))
    if any_tags:
        entries = entries.filter(tags__overlap=any_tags)

    include_tags = request.GET.getlist("include_tag")
    if include_tags:
        entries = entries.filter(tags__contained_by=include_tags)

    exclude_tags = request.GET.getlist("exclude_tag")
    if exclude_tags:
        entries = entries.exclude(tags__contained_by=exclude_tags)

    planning_group = [
        group for group in params.getlist("planning_group") if group
    ]
    if any(group not in PLANNING_GROUPS for group in planning_group):
        raise BadRequest("Unknown planning category.")
    investment_related = filter_form.cleaned_data["investment_related"]
    if planning_group or investment_related is not None:
        try:
            planning_tags = get_planning_tags()
        except ImproperlyConfigured as error:
            raise BadRequest(str(error)) from error
    if investment_related is True:
        entries = entries.filter(tags__contains=[planning_tags["investment"]])
    elif investment_related is False:
        entries = entries.exclude(tags__contains=[planning_tags["investment"]])

    for group in planning_group:
        entries = entries.filter(planning_group_query(group))
    planning_tag = params.get("planning_tag")
    if planning_tag:
        entries = entries.filter(tags__0=planning_tag)

    start = filter_form.cleaned_data["start"]
    if start:
        entries = entries.filter(when__gte=start)

    end = filter_form.cleaned_data["end"]
    if end:
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
        "planning_group": planning_group,
        "planning_tag": planning_tag,
        "q": q,
        "qs": params.urlencode(),
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


def paginate_results(request, objects):
    try:
        page_size = abs(int(request.GET.get("page_size"))) or ENTRIES_PER_PAGE
    except (ValueError, TypeError):
        page_size = ENTRIES_PER_PAGE
    paginator = Paginator(objects, page_size)
    page_obj = paginator.get_page(request.GET.get("page"))
    page = page_obj.number

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

    return {
        "page_obj": page_obj,
        "page_range": range(start, end + 1),
        "page_size": page_size,
        "page_start": start,
        "page_end": end,
    }


def list_filter_context(request, filters):
    when = filters["when"]
    if when:
        when_next = when + timedelta(days=1) if when < date.max else None
        when_prev = when - timedelta(days=1) if when > date.min else None
    else:
        when_next = None
        when_prev = None
    active_filters = []
    for name, label in (
        ("q", "Search"),
        ("when", "Date"),
        ("account", "Account"),
        ("tag", "Tag"),
        ("month", "Month"),
        ("year", "Year"),
        ("country", "Country"),
        ("who", "Person"),
        ("currency", "Currency"),
        ("asset", "Asset"),
        ("include_tag", "Include tag"),
        ("exclude_tag", "Exclude tag"),
        ("is_income", "Income"),
        ("investment_related", "Investment related"),
        ("asset_present", "Has asset"),
        ("tag_any", "Any tag"),
        ("planning_group", "Report category"),
        ("planning_tag", "Report tag"),
        ("start", "From"),
        ("end", "Until"),
    ):
        for value in dict.fromkeys(request.GET.getlist(name)):
            if not value:
                continue
            params = request.GET.copy()
            params.setlist(
                name, [item for item in params.getlist(name) if item != value]
            )
            display_value = value
            if name == "planning_group":
                display_value = PLANNING_GROUPS.get(value, value)
            if name in {"is_income", "investment_related", "asset_present"}:
                if filters[name] is not None:
                    display_value = "Yes" if filters[name] else "No"
            if name in {"when", "start", "end"} and filters[name]:
                display_value = filters[name].isoformat()
            active_filters.append(
                {
                    "name": name,
                    "label": f"{label}: {display_value}",
                    "href": "?" + params.urlencode(),
                }
            )
    return {
        "active_filters": active_filters,
        "search_form": EntryFilterForm(
            initial={"when": when}, auto_id="search-%s", label_suffix=""
        ),
        "search_filters": [
            (key, value)
            for key, values in request.GET.lists()
            if key not in {"q", "when"}
            for value in values
        ],
        "when_next": when_next,
        "when_prev": when_prev,
    }


@require_http_methods(["GET", "POST"])
@login_required
def entries(request, book_slug):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)
    entries, filters, available = parse_request(request, book)
    accounts = Account.objects.by_book(book)
    assets = Asset.objects.by_book(book)
    update_selection = (
        request.method == "POST"
        and request.htmx
        and "update-selection" in request.POST
    )
    selected_ids = set()
    if update_selection:
        try:
            selected_ids = {int(pk) for pk in request.POST.getlist("entry")}
        except ValueError:
            return HttpResponseBadRequest("Invalid entry selection.")
    form_data = request.POST if request.method == "POST" else None

    edit_account_form = ChooseForm(
        queryset=accounts,
        data=form_data,
        prefix="account",
        label="Account",
    )
    edit_asset_form = ChooseForm(
        queryset=assets,
        data=form_data,
        prefix="asset",
        label="Asset",
    )
    edit_tags_form = ChooseForm(
        choices=ChoicesMixin.TAG_CHOICES,
        data=form_data,
        prefix="tags",
        label="Tag",
    )
    edit_country_form = ChooseForm(
        choices=ChoicesMixin.COUNTRY_CHOICES,
        data=form_data,
        prefix="country",
        label="Country",
    )

    if request.method == "POST" and not update_selection:
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

        context = {
            "book": book,
            "entries": entries,
            "qs": filters["qs"],
            "filters": filters,
        }
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
            template = "gemcore/entries.html#selection_balance"
            context["selected_count"] = len(ids)
            entries = entries.select_related("account")
            currencies = entries.values_list(
                "account__currency", flat=True
            ).distinct()
            if len(currencies) < 2:
                context["balance"] = book.balance(entries)
            else:
                context["balances"] = {
                    currency: book.balance(
                        entries.filter(account__currency=currency)
                    )
                    for currency in currencies
                }

        else:
            raise Http404()

        return render(request, template, context)

    # Selection updates share pagination so they stay scoped to this page.
    entries = entries.order_by(*ENTRY_ORDERING)

    pagination = paginate_results(request, entries)
    entries = pagination["page_obj"]

    page_ids = {entry.pk for entry in entries}
    selected_ids &= page_ids
    if update_selection:
        selection_action = request.POST["update-selection"]
        if selection_action == "page":
            selected_ids = (
                page_ids if request.POST.get("select-page") == "all" else set()
            )
        elif selection_action == "clear":
            selected_ids = set()

    currencies = [c for c, i in available["currencies"]]
    context = {
        "book": book,
        "filters": filters,
        "available": available,
        "entries": entries,
        "selected_ids": selected_ids,
        "selected_count": len(selected_ids),
        "all_selected": bool(page_ids) and selected_ids == page_ids,
        "no_selection": not selected_ids,
        "cannot_merge": len(selected_ids) < 2,
        "edit_account_form": edit_account_form,
        "edit_asset_form": edit_asset_form,
        "edit_tags_form": edit_tags_form,
        "edit_country_form": edit_country_form,
        "account_balance_form": AccountBalanceForm(queryset=accounts),
        "currency_balance_form": CurrencyBalanceForm(choices=currencies),
    }
    context.update(pagination)
    context.update(list_filter_context(request, filters))
    for name, form in (
        ("account", edit_account_form),
        ("asset", edit_asset_form),
        ("tags", edit_tags_form),
        ("country", edit_country_form),
    ):
        context[f"cannot_change_{name}"] = not (
            selected_ids and form.is_valid() and form.cleaned_data["target"]
        )
    if update_selection:
        return render(request, "gemcore/entries.html#entry_selection", context)
    return render(request, "gemcore/entries.html", context)


@require_GET
@login_required
def entry_country(request, book_slug):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)
    country = request.GET.get("country", "")
    account_id = request.GET.get("account")
    if account_id:
        try:
            account_id = int(account_id)
        except ValueError:
            raise Http404("Invalid account.")
        account = get_object_or_404(
            Account.objects.by_book(book), pk=account_id
        )
        country = COUNTRY_BY_CURRENCY.get(account.currency, country)
    form = EntryForm(book=book, initial={"country": country})
    return render(request, "gemcore/entry.html#entry_country", {"form": form})


@require_http_methods(["GET", "POST"])
@login_required
def entry(request, book_slug, entry_id=None):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)
    entry = None
    if entry_id:
        entry = get_object_or_404(Entry, book=book, id=entry_id)

    params = request.GET.copy()
    # Date defaults for another entry must not change the return filters.
    params.pop("initial_when", None)
    qs = request.POST.get("qs", params.urlencode())
    context = dict(book=book, entry=entry, qs=qs)
    if entry:
        filtered, _, _ = parse_request(request, book)
        if filtered.filter(pk=entry.pk).exists():
            before = (
                Q(when__gt=entry.when)
                | Q(when=entry.when, what__lt=entry.what)
                | Q(when=entry.when, what=entry.what, pk__lt=entry.pk)
            )
            after = (
                Q(when__lt=entry.when)
                | Q(when=entry.when, what__gt=entry.what)
                | Q(when=entry.when, what=entry.what, pk__gt=entry.pk)
            )
            context["entry_prev"] = (
                filtered.filter(before)
                .order_by(*ENTRY_ORDERING)
                .reverse()
                .first()
            )
            context["entry_next"] = (
                filtered.filter(after).order_by(*ENTRY_ORDERING).first()
            )

    if request.method == "POST":
        form = EntryForm(instance=entry, book=book, data=request.POST)
        if form.is_valid():
            entry = form.save()
            if entry is not None:
                kwargs = dict(book_slug=book_slug)
                return_params = QueryDict(qs, mutable=True)
                if "save-and-new" in request.POST:
                    url = reverse("add-entry", kwargs=kwargs)
                elif "save-and-new-same-date" in request.POST:
                    url = reverse("add-entry", kwargs=kwargs)
                    return_params["initial_when"] = entry.when.isoformat()
                elif "save-and-edit" in request.POST:
                    kwargs["entry_id"] = entry.id
                    url = reverse("entry", kwargs=kwargs)
                else:
                    url = reverse("entries", kwargs=kwargs)
                if return_params:
                    url += "?" + return_params.urlencode()
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
            if account is not None:
                initial["country"] = COUNTRY_BY_CURRENCY.get(
                    account.currency, ""
                )
            when = request.GET.get("initial_when") or request.GET.get("when")
            if when:
                initial["when"] = when

        if entry and not entry.country:
            initial["country"] = COUNTRY_BY_CURRENCY.get(
                entry.account.currency, ""
            )
        form = EntryForm(instance=entry, book=book, initial=initial)

    context["form"] = form
    return render(request, "gemcore/entry.html", context)


@require_http_methods(["GET", "POST"])
@login_required
def entry_remove(request, book_slug, entry_id=None):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)
    entries = book.entry_set.all()
    qs = request.GET.urlencode()
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
            reverse("entries", args=(book.slug,)) + "?" + qs
        )

    return render(
        request,
        "gemcore/remove-entries.html",
        dict(entries=entries, book=book, qs=qs),
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

    context = dict(form=form, book=book)
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
            tags = [settings.ENTRY_TAGS["transfer"]]

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

    context = dict(form=form, book=book)
    return render(request, "gemcore/transfer.html", context)


@require_http_methods(["GET", "POST"])
@login_required
def balance(
    request, book_slug, account_slug=None, currency=None, start=None, end=None
):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)
    accounts = Account.objects.by_book(book)
    currencies = sorted(set(accounts.values_list("currency", flat=True)))

    form = None
    if request.method == "POST":
        if "get-account-balance" in request.POST:
            form = AccountBalanceForm(
                queryset=accounts, data=request.POST, auto_id="id_account_%s"
            )
        elif "get-currency-balance" in request.POST:
            form = CurrencyBalanceForm(
                choices=currencies, data=request.POST, auto_id="id_currency_%s"
            )
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
            qs = request.GET.copy()
            source_currency = (
                source.currency if isinstance(source, Account) else source
            )
            if qs.get("currency") and qs["currency"] != source_currency:
                qs.pop("currency")
            if qs.get("account"):
                if isinstance(source, Account):
                    compatible = qs["account"] == source.slug
                else:
                    compatible = accounts.filter(
                        slug=qs["account"], currency=source
                    ).exists()
                if not compatible:
                    qs.pop("account")
            if start:
                qs["start"] = start
            else:
                qs.pop("start", None)
            if end:
                qs["end"] = end
            else:
                qs.pop("end", None)
            if qs:
                url += "?" + qs.urlencode()
            return HttpResponseRedirect(url)

    chosen_accounts = None
    if account_slug:
        chosen_accounts = accounts.filter(slug=account_slug)
    elif currency:
        chosen_accounts = accounts.filter(currency=currency)

    if chosen_accounts is not None and not chosen_accounts.exists():
        raise Http404

    scope = (
        {"account__in": chosen_accounts} if chosen_accounts is not None else {}
    )
    entries, filters, available = parse_request(request, book, **scope)
    balance = book.balance(entries) if chosen_accounts is not None else None
    pagination = paginate_results(
        request, list(reversed(balance["months"])) if balance else []
    )

    account_balance_form = AccountBalanceForm(
        queryset=accounts,
        initial=dict(
            source=account_slug, start=filters["start"], end=filters["end"]
        ),
        auto_id="id_account_%s",
    )
    currency_balance_form = CurrencyBalanceForm(
        choices=currencies,
        initial=dict(
            source=currency, start=filters["start"], end=filters["end"]
        ),
        auto_id="id_currency_%s",
    )
    if isinstance(form, AccountBalanceForm):
        account_balance_form = form
    elif isinstance(form, CurrencyBalanceForm):
        currency_balance_form = form
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
    context.update(pagination)
    context.update(list_filter_context(request, filters))
    return render(request, "gemcore/balance.html", context)


@require_GET
@login_required
@vary_on_headers("HX-Request", "HX-Boosted")
def planning(request, book_slug, year=None):
    book = get_object_or_404(Book, slug=book_slug, users=request.user)
    entries_url = reverse("entries", args=[book.slug])
    planning_url = reverse("planning", args=[book.slug])
    if year is not None:
        if not 1 <= year <= 9999:
            raise Http404
        params = request.GET.copy()
        params["year"] = year
        return HttpResponseRedirect(planning_url + "?" + params.urlencode())

    try:
        get_planning_tags()
    except ImproperlyConfigured as error:
        return render(
            request,
            (
                "gemcore/planning.html#configuration_error"
                if request.htmx and not request.htmx.boosted
                else "gemcore/planning.html"
            ),
            {"book": book, "planning_error": str(error)},
        )

    entries, filters, available = parse_request(request, book)
    controls = list_filter_context(request, filters)
    context = {
        "available": available,
        "book": book,
        "filters": filters,
        **controls,
    }
    scope_names = {
        "q",
        "account",
        "asset",
        "country",
        "who",
        "tag",
        "include_tag",
        "exclude_tag",
        "is_income",
        "asset_present",
        "tag_any",
        "investment_related",
        "planning_group",
        "planning_tag",
    }
    narrowed = any(
        item["name"] in scope_names for item in controls["active_filters"]
    )
    period_params = request.GET.copy()
    for name in scope_names | {"page", "page_size"}:
        period_params.pop(name, None)
    period_url = planning_url
    if period_params:
        period_url += "?" + period_params.urlencode()

    context.update(narrowed=narrowed, period_url=period_url, planning={})
    if not request.htmx or request.htmx.boosted:
        return render(request, "gemcore/planning.html", context)
    if not filters["currency"]:
        return HttpResponseBadRequest(
            "Choose a currency for the planning report."
        )

    planning = build_planning_summary(entries)

    def entry_link(currency, group, **extra):
        params = request.GET.copy()
        params.pop("page", None)
        params.pop("page_size", None)
        params["currency"] = currency
        groups = params.getlist("planning_group")
        if group not in groups:
            params.setlist("planning_group", [*groups, group])
        for name, value in extra.items():
            params[name] = value
        return entries_url + "?" + params.urlencode()

    for currency, summary in planning.items():
        summary["overview_rows"] = [
            {
                "label": label,
                "amount": summary[key]["amount"],
                "url": entry_link(currency, key),
                "no_expenses": (
                    key == "expenses" and not summary[key].get("count")
                ),
            }
            for key, label in PLANNING_GROUPS.items()
            if key not in {"investment_net", "non_salary_net"}
        ]
        summary["coverage_rows"] = [
            {
                "label": PLANNING_GROUPS["investment_net"],
                "amount": summary["investment_net"]["amount"],
                "url": entry_link(currency, "investment_net"),
                "signed": True,
            },
            {
                "label": PLANNING_GROUPS["non_salary_net"],
                "amount": summary["non_salary_net"]["amount"],
                "url": entry_link(currency, "non_salary_net"),
                "signed": True,
            },
            {
                "label": "Net non-salary cash flow minus expenses",
                "amount": summary["coverage_gap"]["amount"],
            },
            {
                "label": "Net cash flow from all sources minus expenses",
                "amount": summary["net_result"]["amount"],
            },
        ]
        summary["breakdowns"] = []
        for key, label in (
            ("expenses", "Expenses"),
            ("income_total", "Income"),
            ("investment_outflows", "Investment outflows"),
            ("ignored_change", "Ignored transfer movements"),
        ):
            breakdown = (
                "income_by_tag" if key == "income_total" else key + "_by_tag"
            )
            rows = [
                {
                    "label": dict(ChoicesMixin.TAG_CHOICES).get(tag, tag),
                    "amount": amount,
                    "url": entry_link(currency, key, planning_tag=tag),
                }
                for tag, amount in summary[breakdown].items()
            ]
            summary["breakdowns"].append(
                {"title": label + " by tag", "rows": rows}
            )
        for key, label in (
            ("income_rental", "Rental income"),
            ("income_other_investment", "Investment inflows"),
            ("investment_outflows", "Investment outflows"),
        ):
            breakdown = {
                "income_rental": "rental_income_by_asset",
                "income_other_investment": "other_investment_income_by_asset",
                "investment_outflows": "investment_outflows_by_asset",
            }[key]
            rows = [
                {
                    "label": name,
                    "amount": amount,
                    "url": entry_link(currency, key, asset=slug),
                }
                for (slug, name), amount in summary[breakdown].items()
            ]
            summary["breakdowns"].append(
                {"title": label + " by asset", "rows": rows}
            )

    context["planning"] = planning
    return render(request, "gemcore/planning.html#currency_report", context)
