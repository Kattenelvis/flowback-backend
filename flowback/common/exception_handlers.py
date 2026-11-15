"""
Every error the API sends has the same shape:

    {"detail": "title: Ensure this value has at most 255 characters (it has 256).",
     "code": "max_length",
     "errors": [{"field": "title", "message": "Ensure this value has at most 255 characters (it has 256).",
                 "code": "max_length"}]}

detail is always a string that can be shown as is (the first error, prefixed with its field), code is meant for
branching on, and errors has every error with dotted field paths such as "segments.1.proposal_id".
"""
import logging

from django.conf import settings
from django.core.exceptions import (NON_FIELD_ERRORS, BadRequest, ObjectDoesNotExist, PermissionDenied,
                                    SuspiciousOperation, ValidationError as DjangoValidationError)
from django.http import Http404
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.serializers import as_serializer_error
from rest_framework.settings import api_settings
from rest_framework.views import exception_handler, set_rollback

logger = logging.getLogger(__name__)

NON_FIELD_KEYS = (api_settings.NON_FIELD_ERRORS_KEY, NON_FIELD_ERRORS)


def flatten_errors(detail, path=()) -> list[dict]:
    """Turns any DRF error detail into [{"field": "segments.1.proposal_id" or None, "message": str, "code": str}]"""
    if isinstance(detail, dict):
        return [error
                for key, value in detail.items()
                for error in flatten_errors(value, path if key in NON_FIELD_KEYS else (*path, str(key)))]

    if isinstance(detail, list):
        # A list of messages belongs to one field, a list of dicts or lists has one entry per item
        return [error
                for i, item in enumerate(detail)
                for error in flatten_errors(item, (*path, str(i)) if isinstance(item, (dict, list)) else path)]

    return [dict(field='.'.join(path) or None, message=str(detail), code=getattr(detail, 'code', None) or 'error')]


def error_body(exc: exceptions.APIException) -> dict:
    """The only error shape: {"detail": str, "code": str, "errors": [{"field", "message", "code"}, ...]}"""
    errors = flatten_errors(exc.detail) or [dict(field=None, message=str(exc.default_detail), code=exc.default_code)]
    first = errors[0]
    detail = f"{first['field']}: {first['message']}" if first['field'] else first['message']

    return dict(detail=detail, code=first['code'], errors=errors)


def to_api_exception(exc: Exception) -> exceptions.APIException | None:
    """Maps Django's exceptions onto DRF's. None means a bug (500)."""
    if isinstance(exc, exceptions.APIException):
        return exc
    if isinstance(exc, DjangoValidationError):
        return exceptions.ValidationError(as_serializer_error(exc))
    if isinstance(exc, Http404):
        return exceptions.NotFound()
    if isinstance(exc, PermissionDenied):
        return exceptions.PermissionDenied()
    if isinstance(exc, ObjectDoesNotExist):
        if settings.DEBUG:
            logger.info("Not found", exc_info=exc)
        return exceptions.NotFound(detail=str(exc))
    if isinstance(exc, (SuspiciousOperation, BadRequest)):  # e.g. more than 1000 form fields or 100 files
        return exceptions.ParseError()
    return None


def drf_default_with_modifications_exception_handler(exc, ctx):
    api_exc = to_api_exception(exc)

    if api_exc is None:  # Unexpected errors, answered in the same shape instead of Django's HTML or text page
        logger.error("Unhandled exception", exc_info=exc)
        set_rollback()
        api_exc = exceptions.APIException(f"{type(exc).__name__}: {exc}" if settings.DEBUG else None)
        response = Response(status=api_exc.status_code)
    else:
        response = exception_handler(api_exc, ctx)  # Keeps DRF's status codes and headers

    response.data = error_body(api_exc)
    return response
