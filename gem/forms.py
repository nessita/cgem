"""Centralize form styling, including Django's authentication forms."""

from django import forms
from django.forms.renderers import DjangoTemplates

INPUT_CLASSES = (
    "bg-white block border border-stone-300 focus:border-stone-500 "
    "focus:outline-none focus:ring-2 focus:ring-stone-200 px-3 py-2 "
    "rounded-md text-sm w-full"
)
CHOICE_CLASSES = (
    "accent-sky-700 focus:outline-none focus:ring-2 focus:ring-stone-200"
)
LABEL_CLASSES = "block font-medium text-stone-700 text-sm"


class TailwindBoundField(forms.BoundField):
    def build_widget_attrs(self, attrs, widget=None):
        attrs = super().build_widget_attrs(attrs, widget)
        widget = widget or self.field.widget
        if not widget.is_hidden:
            if getattr(widget, "input_type", None) in {"checkbox", "radio"}:
                classes = CHOICE_CLASSES
            else:
                classes = INPUT_CLASSES
            existing = attrs.get("class", widget.attrs.get("class", ""))
            attrs["class"] = f"{existing} {classes}".strip()
        return attrs

    def label_tag(
        self, contents=None, attrs=None, label_suffix=None, tag=None
    ):
        attrs = {**(attrs or {})}
        attrs["class"] = f"{attrs.get('class', '')} {LABEL_CLASSES}".strip()
        return super().label_tag(contents, attrs, label_suffix, tag)


class TailwindFormRenderer(DjangoTemplates):
    bound_field_class = TailwindBoundField
    field_template_name = "forms/field.html"
    form_template_name = "forms/form.html"
