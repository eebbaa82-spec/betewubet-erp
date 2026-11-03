from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog import demo_data


class Command(BaseCommand):
    help = "Load sample units, work centers, materials, cabinet templates, opening stock, suppliers and machines."

    @transaction.atomic
    def handle(self, *args, **options):
        demo_data.load()
        demo_data.load_stock()
        demo_data.load_suppliers()
        demo_data.load_machines()
        self.stdout.write(self.style.SUCCESS("Sample data loaded. Prices are illustrative, not real supplier prices."))
