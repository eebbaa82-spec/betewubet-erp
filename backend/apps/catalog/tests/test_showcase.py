from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.catalog import showcase
from apps.dispatch import services as dispatch
from apps.finance import services as finance
from apps.finance.models import Invoice
from apps.production.models import TimeLog, WorkOrder
from apps.sales.models import SalesOrder

pytestmark = pytest.mark.django_db


def test_showcase_fills_every_stage():
    showcase.load()
    statuses = set(SalesOrder.objects.values_list("status", flat=True))
    assert {"quote", "confirmed", "dispatched", "installed"} <= statuses
    assert set(WorkOrder.objects.values_list("status", flat=True)) >= {"planned", "in_progress", "done"}
    assert TimeLog.objects.filter(ended_at__isnull=True).count() == 1  # the spray booth is running
    [ready] = dispatch.ready_to_ship()
    assert any(Decimal(l["awaiting_inspection"]) > 0 for l in ready["lines"])
    assert Invoice.objects.filter(status="draft").count() == 1
    aging = finance.receivables()["totals"]
    assert Decimal(aging["d60"]) > 0 and Decimal(aging["current"]) > 0
    assert finance.to_bill()
    with pytest.raises(ValidationError, match="empty database"):
        showcase.load()
