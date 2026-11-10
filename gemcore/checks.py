from django.conf import settings
from django.core.checks import Error

from gemcore.constants import get_tag_choices


def tag_configuration_errors():
    config = settings.ENTRY_TAGS
    if not isinstance(config, dict):
        return [
            "ENTRY_TAGS must be a dictionary with keys: choices, default, and "
            "transfer."
        ]
    choices = get_tag_choices()
    if not choices or any(
        not isinstance(choice, (list, tuple))
        or len(choice) != 2
        or not isinstance(choice[0], str)
        or not choice[0]
        or len(choice[0]) > 256
        or not isinstance(choice[1], str)
        or not choice[1]
        for choice in choices
    ):
        return [
            "ENTRY_TAGS['choices'] must contain nonempty category codes "
            "and labels."
        ]
    codes = [code for code, label in choices]
    if len(set(codes)) != len(codes):
        return ["ENTRY_TAGS['choices'] must have unique category codes."]
    errors = []
    for role in ("default", "transfer"):
        code = config.get(role)
        if not isinstance(code, str) or code not in codes:
            errors.append(
                f"ENTRY_TAGS['{role}'] must reference a code "
                "in ENTRY_TAGS['choices']."
            )
    if not errors and config["default"] == config["transfer"]:
        errors.append("The default and transfer categories must be distinct.")
    return errors


def check_entry_tags(app_configs, **kwargs):
    return [
        Error(message, id="gemcore.E001")
        for message in tag_configuration_errors()
    ]
