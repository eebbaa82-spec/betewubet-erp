from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog import showcase


class Command(BaseCommand):
    help = ("Load the sample master data plus a made-up month of orders, production, inspections, deliveries, "
            "invoices, purchases and machine service, dated relative to today. Needs an empty database.")

    @transaction.atomic
    def handle(self, *args, **options):
        showcase.load()
        self.stdout.write(self.style.SUCCESS(
            "Showcase loaded. All customers, suppliers, TINs and prices are invented."))
