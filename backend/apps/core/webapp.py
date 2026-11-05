"""Serve the built web app (frontend/dist/index.html) for every page address, so links such as
/work-orders/12 work when opened directly or refreshed. Its scripts and styles are static files."""
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, HttpResponseNotFound
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie


@never_cache
@ensure_csrf_cookie
def index(request):
    page = Path(settings.FRONTEND_DIST) / "index.html"
    if not page.is_file():
        return HttpResponseNotFound(
            "The web app has not been built. Run `npm run build` in frontend/ (with VITE_APP_ROOT set "
            "to the URL prefix), then `python manage.py collectstatic`.", content_type="text/plain")
    return HttpResponse(page.read_text(encoding="utf-8"))
