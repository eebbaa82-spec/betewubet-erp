"""Startup file for cPanel "Setup Python App".

Enter app_wsgi.py as the *Application startup file*, not passenger_wsgi.py: cPanel writes its own
passenger_wsgi.py that loads the startup file, so naming passenger_wsgi.py there makes it load
itself in a loop."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from config.wsgi import application  # noqa: E402,F401
