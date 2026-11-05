"""Entry point for cPanel "Setup Python App" (Phusion Passenger).

Passenger looks for a module called passenger_wsgi with an ``application`` object in the
application root, which should be this backend/ folder."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from config.wsgi import application  # noqa: E402,F401
