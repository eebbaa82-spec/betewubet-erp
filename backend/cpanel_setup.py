"""One-time (and after every update) setup for cPanel hosting.

Run it from cPanel > Setup Python App > "Execute python script" (enter: cpanel_setup.py),
or in Terminal inside the app's virtual environment:  python cpanel_setup.py

It creates or updates the database tables, copies the web app and admin styles into place,
and on the first run creates an "admin" user with a random password, which it prints and
saves to FIRST_LOGIN.txt next to this file. Add --sample to load the made-up sample month
(only on an empty database)."""
import os
import secrets
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.core.management import call_command  # noqa: E402


def main():
    print("1/3 Database tables")
    call_command("migrate", interactive=False, verbosity=1)
    print("2/3 Web app and admin files")
    call_command("collectstatic", interactive=False, verbosity=0)
    print("3/3 Sign-in")
    User = get_user_model()
    if not User.objects.filter(is_superuser=True).exists():
        password = secrets.token_urlsafe(12)
        User.objects.create_superuser("admin", "", password)
        note = f"User name: admin\nPassword: {password}\nChange it after signing in (Back office > Users).\n"
        (HERE / "FIRST_LOGIN.txt").write_text(note)
        print(note)
    else:
        print("An admin user already exists; nothing to do.")
    if "--sample" in sys.argv:
        from apps.sales.models import SalesOrder

        if SalesOrder.objects.exists():
            print("Sample data skipped: the database already has orders, so it was probably loaded already.")
        else:
            call_command("seed_showcase")
    elif "--master-data" in sys.argv:
        call_command("seed_demo")
    print("Done. Restart the app in Setup Python App.")


if __name__ == "__main__":
    main()
