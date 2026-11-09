import subprocess

from django.shortcuts import get_object_or_404
from django.utils.functional import cached_property
from rest_framework import mixins, status, viewsets
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import APIView

from gemapi.serializers import EntryFilterSerializer, EntrySerializer
from gemcore.models import Book, Entry


class EntryPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100

    def paginate_queryset(self, queryset, request, view=None):
        self.params = view.entry_filters
        return super().paginate_queryset(queryset, request, view=view)

    def get_page_size(self, request):
        return self.params.get("page_size", self.page_size)

    def get_page_number(self, request, paginator):
        return self.params.get("page", 1)


class EntriesView(
    mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = EntrySerializer
    pagination_class = EntryPagination
    queryset = Entry.objects.none()

    @cached_property
    def book(self):
        books = self.request.user.book_set.all()
        slug = self.kwargs.get("book_slug")
        if slug:
            return get_object_or_404(books, slug=slug)
        defaults = books.filter(default=True)
        if defaults.exists():
            books = defaults
        try:
            return get_object_or_404(books)
        except Book.MultipleObjectsReturned:
            raise ValidationError(
                {
                    "book": "A book cannot be selected unambiguously. "
                    "Use /api/<book_slug>/entries/."
                }
            ) from None

    def get_serializer_context(self):
        return {
            **super().get_serializer_context(),
            "book": self.book,
            "book_slug": self.kwargs.get("book_slug"),
        }

    @cached_property
    def entry_filters(self):
        params = self.request.query_params.copy()
        params.pop("book", None)
        if api_settings.URL_FORMAT_OVERRIDE:
            params.pop(api_settings.URL_FORMAT_OVERRIDE, None)
        filters = EntryFilterSerializer(data=params)
        filters.is_valid(raise_exception=True)
        return filters.validated_data

    def get_queryset(self):
        entries = self.book.entry_set.select_related("book", "account", "who")
        lookups = {
            "account": "account__slug",
            "start": "when__gte",
            "end": "when__lte",
            "country": "country",
            "currency": "account__currency",
            "who": "who__username",
            "tag": "tags__contains",
            "is_income": "is_income",
        }
        entries = entries.filter(
            **{
                lookups[name]: value
                for name, value in self.entry_filters.items()
                if name in lookups
            }
        )
        return entries.order_by("-when", "what", "id")

    def perform_create(self, serializer):
        serializer.save(who=self.request.user)

    def create(self, request, *args, **kwargs):
        if not isinstance(request.data, list):
            return super().create(request, *args, **kwargs)
        context = self.get_serializer_context()
        if not request.data:
            raise ValidationError("Provide at least one entry.")
        result = {"entries": [], "errors": []}
        for index, data in enumerate(request.data):
            serializer = self.get_serializer(data=data, context=context)
            try:
                serializer.is_valid(raise_exception=True)
                self.perform_create(serializer)
            except ValidationError as error:
                result["errors"].append(
                    {"index": index, "errors": error.detail}
                )
            else:
                result["entries"].append(serializer.data)
        if not result["errors"]:
            response_status = status.HTTP_201_CREATED
        elif result["entries"]:
            response_status = status.HTTP_200_OK
        else:
            response_status = status.HTTP_400_BAD_REQUEST
        return Response(result, status=response_status)


class VersionView(APIView):
    def get(self, request, format=None):
        git_hash = (
            subprocess.check_output(["git", "rev-parse", "--short", "HEAD"])
            .decode("ascii")
            .strip()
        )
        return Response(git_hash)
