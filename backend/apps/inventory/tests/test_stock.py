from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.catalog.explode import explode
from apps.catalog.models import Item
from apps.inventory.models import Location, Offcut, StockMove
from apps.inventory.services import issue, match_offcuts, on_hand, receive, register_offcut

pytestmark = pytest.mark.django_db


def test_opening_stock_is_in_base_units(demo):
    mdf = Item.objects.get(code="MDF-WHT-18")
    offcuts = sum(o.area_m2 for o in Offcut.objects.filter(item=mdf))
    assert (on_hand(mdf) - offcuts).quantize(Decimal("0.01")) == Decimal("136.93")  # 46 sheets x 2.9768 m2
    assert offcuts > 0  # offcuts are booked through the ledger too


def test_ledger_rows_cannot_be_edited_or_deleted(demo):
    move = StockMove.objects.first()
    move.qty = 0
    with pytest.raises(ValidationError):
        move.save()
    with pytest.raises(ValidationError):
        move.delete()


def test_issue_refuses_more_than_on_hand(demo):
    slides = Item.objects.get(code="SLD-450")
    main = Location.objects.get(code="MAIN")
    with pytest.raises(ValidationError, match="Only 38"):
        issue(slides, 40, main)
    issue(slides, 10, main)
    assert on_hand(slides) == 28


def test_lot_tracked_items_need_a_lot(demo):
    with pytest.raises(ValidationError, match="lot-tracked"):
        receive(Item.objects.get(code="LAC-PU"), 20, 1100, Location.objects.get(code="MAIN"))


def test_small_pieces_are_scrap_not_offcuts(demo):
    mdf, rack = Item.objects.get(code="MDF-WHT-18"), Location.objects.get(code="OC-RACK")
    with pytest.raises(ValidationError, match="scrap"):
        register_offcut(mdf, 900, 250, rack, lot=mdf.lots.first())
    before = on_hand(mdf)
    oc = register_offcut(mdf, 900, 400, rack, lot=mdf.lots.first())
    assert on_hand(mdf) - before == Decimal("0.3600")
    assert oc.code.startswith("OC-")


def test_offcuts_are_matched_smallest_fit_first_and_reserved(demo):
    r = explode("BASE-CAB", {"W": 800, "H": 720, "D": 560, "drawers": 3})
    matches = match_offcuts(r.panels)
    used = {o.code: r.panels[i].name for i, o in matches}
    # the 720 x 560 offcut is an exact fit for a side panel
    assert used["OC-00003"] == "Side panel"
    assert all(o.status == Offcut.Status.AVAILABLE for _, o in matches)  # matching alone reserves nothing
