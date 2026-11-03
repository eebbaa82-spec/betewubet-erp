from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.catalog.explode import explode
from apps.production import costing

pytestmark = pytest.mark.django_db

DRAWER_UNIT = {"W": 800, "H": 720, "D": 560, "board": "MDF-WHT-18", "front": "mel", "drawers": 3, "handle": "bar"}


def panel(result, name):
    return next(p for p in result.panels if p.name == name)


def test_carcass_sizes_follow_dimensions_and_board_thickness(demo):
    r = explode("BASE-CAB", DRAWER_UNIT)
    side, bottom = panel(r, "Side panel"), panel(r, "Bottom")
    assert (side.length_mm, side.width_mm, side.qty) == (Decimal("720.0"), Decimal("560.0"), 2)
    assert bottom.length_mm == Decimal("764.0")  # 800 - 2 x 18 mm
    assert side.edge_m == Decimal("1.4400")  # front edge of both sides


def test_drawer_boxes_come_from_the_sub_assembly(demo):
    r = explode("BASE-CAB", DRAWER_UNIT)
    sides = panel(r, "Drawer side")
    assert sides.path == "Drawers > Drawer box"
    assert sides.qty == 6  # 2 per box x 3 drawers
    assert sides.length_mm == Decimal("500.0")  # depth 560 - 60
    slides = next(i for i in r.items if i.item_code == "SLD-450")
    assert slides.qty == 3


def test_doors_replace_drawers_and_bring_hinges_and_a_shelf(demo):
    r = explode("BASE-CAB", {**DRAWER_UNIT, "drawers": 0})
    names = {p.name for p in r.panels}
    assert "Door" in names and "Shelf" in names and "Drawer front" not in names
    assert panel(r, "Door").qty == 2  # wider than 600 mm
    hinges = next(i for i in r.items if i.item_code == "HNG-SC-110")
    assert hinges.qty == 4


def test_lacquer_fronts_switch_material_and_add_spray_operation(demo):
    r = explode("BASE-CAB", {**DRAWER_UNIT, "front": "lac"})
    assert panel(r, "Drawer front, lacquered").item_code == "MDF-RAW-18"
    assert "LAC-PU" in r.material_totals()
    assert "SPRAY" in r.minutes_by_work_center()
    assert "SPRAY" not in explode("BASE-CAB", DRAWER_UNIT).minutes_by_work_center()


def test_quantity_scales_everything(demo):
    one, four = explode("BASE-CAB", DRAWER_UNIT), explode("BASE-CAB", DRAWER_UNIT, qty=4)
    diff = four.material_totals()["MDF-WHT-18"] - one.material_totals()["MDF-WHT-18"] * 4
    assert abs(diff) < Decimal("0.001")  # totals are rounded to 4 decimals
    assert four.minutes_by_work_center()["SAW"] == one.minutes_by_work_center()["SAW"] * 4


def test_defaults_fill_missing_parameters(demo):
    r = explode("BASE-CAB", {})
    assert r.params["W"] == 800.0 and r.params["board"] == "MDF-WHT-18"


@pytest.mark.parametrize("params, message", [
    ({"W": 2000}, "at most 1200"),
    ({"front": "gold"}, "must be one of"),
    ({"board": "PLY-XXX"}, "no active item"),
    ({"board": "HDF-WHT-3"}, "not allowed"),
    ({"colour": "red"}, "Unknown parameter"),
])
def test_invalid_configurations_are_refused(demo, params, message):
    with pytest.raises(ValidationError, match=message):
        explode("BASE-CAB", params)


def test_estimate_breaks_cost_down_and_adds_overhead(demo):
    est = costing.estimate(explode("BASE-CAB", DRAWER_UNIT))
    parts = sum(Decimal(est[k]) for k in ("material", "labour", "machine"))
    assert Decimal(est["overhead"]) == (parts * Decimal("0.12")).quantize(Decimal("0.01"))
    assert Decimal(est["total"]) == parts + Decimal(est["overhead"])
    assert Decimal(est["material"]) > Decimal(est["labour"])  # sanity check on sample rates
