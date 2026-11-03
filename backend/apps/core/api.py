from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.views import exception_handler as drf_handler


def exception_handler(exc, context):
    """Return Django ValidationErrors raised in services as 400s with readable messages."""
    if isinstance(exc, DjangoValidationError):
        exc = serializers.ValidationError({"detail": exc.messages})
    return drf_handler(exc, context)


# --- Sign-in for the web app (session cookie + CSRF) -------------------------
from django.contrib.auth import authenticate, login, logout  # noqa: E402
from django.utils.decorators import method_decorator  # noqa: E402
from django.views.decorators.csrf import ensure_csrf_cookie  # noqa: E402
from rest_framework import permissions, status  # noqa: E402
from rest_framework.response import Response  # noqa: E402
from rest_framework.views import APIView  # noqa: E402


def _user(u):
    return {"id": u.id, "username": u.username, "name": u.get_full_name() or u.username,
            "is_staff": u.is_staff}


@method_decorator(ensure_csrf_cookie, name="dispatch")
class MeView(APIView):
    """Who is signed in. Also sets the CSRF cookie the web app sends back on writes."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        if not request.user.is_authenticated:
            return Response({"user": None})
        return Response({"user": _user(request.user)})


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        user = authenticate(request, username=request.data.get("username", ""),
                            password=request.data.get("password", ""))
        if user is None:
            return Response({"detail": "Wrong username or password."}, status=status.HTTP_400_BAD_REQUEST)
        login(request, user)
        return Response({"user": _user(user)})


class LogoutView(APIView):
    def post(self, request):
        logout(request)
        return Response({"user": None})


from rest_framework.pagination import PageNumberPagination  # noqa: E402


class Pagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500
