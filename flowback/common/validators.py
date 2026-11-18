import unicodedata

from django.core.exceptions import ValidationError


def FieldNotBlankValidator(value):
    if value is not None and not value.strip():
        raise ValidationError("This field cannot be blank")


# Letters that Unicode counts as alphanumeric (so they pass \w) but that render as blank:
# Hangul choseong filler, Hangul jungseong filler, Hangul filler, halfwidth Hangul filler
BLANK_LETTERS = {'\u115f', '\u1160', '\u3164', '\uffa0'}


def FieldNoInvisibleCharactersValidator(value):
    """Rejects whitespace, control and formatting characters (zero-width spaces, direction overrides, etc.)
    and letters that render as blank, so a value can't look identical to another or look empty"""
    for character in value or '':
        # C* is control, formatting, private use and unassigned. Z* is every kind of space and separator
        if unicodedata.category(character)[0] in 'CZ' or character in BLANK_LETTERS:
            raise ValidationError("This field cannot contain invisible characters")
