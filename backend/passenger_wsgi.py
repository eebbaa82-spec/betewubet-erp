"""Entry point for Phusion Passenger. cPanel usually replaces this file with its own loader for
the startup file (app_wsgi.py), which works the same way."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app_wsgi import application  # noqa: E402,F401
