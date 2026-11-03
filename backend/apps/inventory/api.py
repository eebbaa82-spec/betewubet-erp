from django.utils import timezone
from rest_framework import mixins, serializers, viewsets

from .models import Location, Lot, Offcut, StockMove


class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Location
        fields = "__all__"


class LotSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lot
        fields = "__all__"


class StockMoveSerializer(serializers.ModelSerializer):
    value = serializers.DecimalField(max_digits=20, decimal_places=2, read_only=True)

    class Meta:
        model = StockMove
        fields = "__all__"
        read_only_fields = ["created_at", "created_by"]

    def create(self, validated):
        validated["created_by"] = self.context["request"].user
        return super().create(validated)


class OffcutSerializer(serializers.ModelSerializer):
    area_m2 = serializers.DecimalField(max_digits=10, decimal_places=4, read_only=True)
    item_code = serializers.CharField(source="item.code", read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)
    lot_code = serializers.CharField(source="lot.code", read_only=True, default="")
    source_work_order_number = serializers.CharField(source="source_work_order.number", read_only=True, default="")

    class Meta:
        model = Offcut
        fields = "__all__"


class LocationViewSet(viewsets.ModelViewSet):
    queryset = Location.objects.all()
    serializer_class = LocationSerializer


class LotViewSet(viewsets.ModelViewSet):
    queryset = Lot.objects.select_related("item")
    serializer_class = LotSerializer


class StockMoveViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                       viewsets.GenericViewSet):
    """The ledger can be read and appended to, never edited."""

    queryset = StockMove.objects.select_related("item", "lot", "location")
    serializer_class = StockMoveSerializer


class OffcutViewSet(viewsets.ModelViewSet):
    queryset = Offcut.objects.select_related("item", "location", "lot", "source_work_order")
    serializer_class = OffcutSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("item"):
            qs = qs.filter(item__code=p["item"])
        return qs


# --- Stock summary and stock actions used by the web app ---------------------
from decimal import Decimal  # noqa: E402

from django.db import transaction  # noqa: E402
from django.db.models import Sum  # noqa: E402
from rest_framework import status  # noqa: E402
from rest_framework.response import Response  # noqa: E402
from rest_framework.views import APIView  # noqa: E402

from apps.catalog.models import Item  # noqa: E402
from apps.production.models import WorkOrder  # noqa: E402

from . import services  # noqa: E402

Q4 = Decimal("0.0001")


def _to_base(item, qty, unit):
    """Convert a quantity in a pack unit (sheet, roll, drum) to the item's base unit."""
    qty = Decimal(str(qty))
    if not unit or unit == item.base_uom.code:
        return qty, Decimal(1)
    conv = item.conversions.filter(name=unit).first()
    if conv is None:
        raise serializers.ValidationError({"unit": f"{item.code} has no unit '{unit}'."})
    return qty * conv.base_qty, conv.base_qty


class StockSummaryView(APIView):
    """On-hand per item, in the base unit and in its pack unit, with lots and value."""

    def get(self, request):
        kind = request.query_params.get("kind")
        items = Item.objects.filter(active=True).select_related("base_uom").prefetch_related("conversions")
        if kind:
            items = items.filter(kind=kind)
        by_lot = {}
        for row in (StockMove.objects.values("item_id", "lot_id", "lot__code", "lot__colour_ref")
                    .annotate(qty=Sum("qty")).order_by("lot__code")):
            if row["qty"]:
                by_lot.setdefault(row["item_id"], []).append(row)
        offcut_area = {}
        for o in Offcut.objects.filter(status__in=[Offcut.Status.AVAILABLE, Offcut.Status.RESERVED]):
            offcut_area[o.item_id] = offcut_area.get(o.item_id, Decimal(0)) + o.area_m2
        out = []
        for item in items:
            lots = by_lot.get(item.id, [])
            on_hand = sum((r["qty"] for r in lots), Decimal(0))
            pack = item.conversions.first()
            cost = services.average_cost(item)
            out.append({
                "code": item.code, "name": item.name, "kind": item.kind, "base_uom": item.base_uom.code,
                "track_lots": item.track_lots,
                "on_hand": str(on_hand.quantize(Q4)),
                "pack": pack.name if pack else None,
                "pack_size": str(pack.base_qty) if pack else None,
                "on_hand_packs": str((on_hand / pack.base_qty).quantize(Decimal("0.01"))) if pack else None,
                "in_offcuts": str(offcut_area.get(item.id, Decimal(0)).quantize(Q4)) if item.kind == "board" else None,
                "unit_cost": str(cost),
                "value": str((on_hand * cost).quantize(Decimal("0.01"))),
                "reorder_level": str(item.reorder_level) if item.reorder_level is not None else None,
                "below_reorder": item.reorder_level is not None and on_hand < item.reorder_level,
                "lots": [{"code": r["lot__code"], "colour_ref": r["lot__colour_ref"] or "",
                          "qty": str(r["qty"].quantize(Q4))} for r in lots if r["lot_id"]],
            })
        return Response(out)


class ReceiveSerializer(serializers.Serializer):
    item = serializers.SlugRelatedField(slug_field="code", queryset=Item.objects.all())
    qty = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=Decimal("0.0001"))
    unit = serializers.CharField(required=False, allow_blank=True, default="")
    unit_cost = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=Decimal("0"),
                                         help_text="ETB per unit given in 'unit'.")
    location = serializers.SlugRelatedField(slug_field="code", queryset=Location.objects.all())
    lot_code = serializers.CharField(required=False, allow_blank=True, default="")
    supplier_batch = serializers.CharField(required=False, allow_blank=True, default="")
    colour_ref = serializers.CharField(required=False, allow_blank=True, default="")
    reference = serializers.CharField(required=False, allow_blank=True, default="")


class ReceiveView(APIView):
    """Goods received: converts pack units to the base unit and creates the lot if new."""

    @transaction.atomic
    def post(self, request):
        s = ReceiveSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        item = d["item"]
        base_qty, per = _to_base(item, d["qty"], d["unit"])
        lot = None
        if item.track_lots:
            if not d["lot_code"]:
                raise serializers.ValidationError({"lot_code": f"{item.code} is lot-tracked; enter the lot or batch."})
            lot, _ = Lot.objects.get_or_create(item=item, code=d["lot_code"], defaults={
                "supplier_batch": d["supplier_batch"], "colour_ref": d["colour_ref"],
                "received_on": timezone.localdate()})
        move = services.receive(item, base_qty, (d["unit_cost"] / per).quantize(Q4), d["location"], lot=lot,
                                reference=d["reference"], user=request.user)
        return Response(StockMoveSerializer(move).data, status=status.HTTP_201_CREATED)


class IssueSerializer(serializers.Serializer):
    work_order = serializers.SlugRelatedField(slug_field="number", queryset=WorkOrder.objects.all())
    item = serializers.SlugRelatedField(slug_field="code", queryset=Item.objects.all())
    qty = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=Decimal("0.0001"))
    unit = serializers.CharField(required=False, allow_blank=True, default="")
    location = serializers.SlugRelatedField(slug_field="code", queryset=Location.objects.all())
    lot_code = serializers.CharField(required=False, allow_blank=True, default="")


class IssueView(APIView):
    """Material issued from stock to a work order (its actual material cost)."""

    def post(self, request):
        s = IssueSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        item = d["item"]
        base_qty, _ = _to_base(item, d["qty"], d["unit"])
        lot = None
        if d["lot_code"]:
            lot = Lot.objects.filter(item=item, code=d["lot_code"]).first()
            if lot is None:
                raise serializers.ValidationError({"lot_code": f"No lot {d['lot_code']} for {item.code}."})
        elif item.track_lots:
            lot = _oldest_lot_with_stock(item, d["location"], base_qty)
        move = services.issue(item, base_qty, d["location"], work_order=d["work_order"], lot=lot, user=request.user)
        return Response(StockMoveSerializer(move).data, status=status.HTTP_201_CREATED)


def _oldest_lot_with_stock(item, location, qty):
    for lot in Lot.objects.filter(item=item).order_by("received_on", "id"):
        if services.on_hand(item, location, lot) >= qty:
            return lot
    raise serializers.ValidationError({"lot_code": f"No single lot of {item.code} at {location} holds {qty}."})


class OffcutRegisterSerializer(serializers.Serializer):
    item = serializers.SlugRelatedField(slug_field="code", queryset=Item.objects.filter(kind="board"))
    length_mm = serializers.IntegerField(min_value=1)
    width_mm = serializers.IntegerField(min_value=1)
    location = serializers.SlugRelatedField(slug_field="code", queryset=Location.objects.all())
    lot_code = serializers.CharField(required=False, allow_blank=True, default="")
    work_order = serializers.SlugRelatedField(slug_field="number", queryset=WorkOrder.objects.all(),
                                              required=False, allow_null=True, default=None)


class OffcutRegisterView(APIView):
    def post(self, request):
        s = OffcutRegisterSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        lot = Lot.objects.filter(item=d["item"], code=d["lot_code"]).first() if d["lot_code"] else None
        if lot is None and d["item"].track_lots:
            # Default to the lot the board was issued from for this job, else the newest lot.
            issued = StockMove.objects.filter(item=d["item"], work_order=d["work_order"], kind=StockMove.Kind.ISSUE,
                                              lot__isnull=False).order_by("-id").first() if d["work_order"] else None
            lot = issued.lot if issued else Lot.objects.filter(item=d["item"]).order_by("-received_on", "-id").first()
        oc = services.register_offcut(d["item"], d["length_mm"], d["width_mm"], d["location"], lot=lot,
                                      work_order=d["work_order"], user=request.user)
        return Response(OffcutSerializer(oc).data, status=status.HTTP_201_CREATED)
