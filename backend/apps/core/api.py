from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.views import exception_handler as drf_handler


def exception_handler(exc, context):
    """Return Django ValidationErrors raised in services as 400s with readable messages."""
    if isinstance(exc, DjangoValidationError):
        exc = serializers.ValidationError({"detail": exc.messages})
    return drf_handler(exc, context)
