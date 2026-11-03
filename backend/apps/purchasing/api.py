from decimal import Decimal

from django.db import transaction
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Item
from apps.inventory.models import Location

from . import services
from .models import PurchaseOrder, PurchaseOrderLine, Supplier, SupplierItem


class SupplierItemSerializer(serializers.ModelSerializer):
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.all())
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    item = serializers.SlugRelatedField(slug_field="code", queryset=Item.objects.all())
    item_name = serializers.CharField(source="item.name", read_only=True)
    uom = serializers.CharField(source="item.base_uom.code", read_only=True)

    class Meta:
        model = SupplierItem
        fields = ["id", "supplier", "supplier_name", "item", "item_name", "uom", "supplier_code", "pack_name",
                  "pack_qty", "price_per_pack", "min_packs", "preferred"]


class SupplierSerializer(serializers.ModelSerializer):
    items = SupplierItemSerializer(many=True, read_only=True)

    class Meta:
        model = Supplier
        fields = ["id", "name", "tin", "vat_registered", "phone", "email", "city", "lead_time_days", "notes",
                  "active", "items"]


class LineSerializer(serializers.ModelSerializer):
    item = serializers.SlugRelatedField(slug_field="code", queryset=Item.objects.all())
    item_name = serializers.CharField(source="item.name", read_only=True)
    uom = serializers.CharField(source="item.base_uom.code", read_only=True)
    track_lots = serializers.BooleanField(source="item.track_lots", read_only=True)
    amount = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    open_packs = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    pack_name = serializers.CharField(required=False)
    pack_qty = serializers.DecimalField(max_digits=14, decimal_places=6, required=False)
    price_per_pack = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)
    packs = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))

    class Meta:
        model = PurchaseOrderLine
        fields = ["id", "item", "item_name", "uom", "track_lots", "pack_name", "pack_qty", "packs", "price_per_pack",
                  "received_packs", "open_packs", "amount"]
        read_only_fields = ["received_packs"]


class OrderSerializer(serializers.ModelSerializer):
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.all())
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    supplier_tin = serializers.CharField(source="supplier.tin", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    lines = LineSerializer(many=True)
    totals = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = ["id", "number", "supplier", "supplier_name", "supplier_tin", "status", "status_label",
                  "order_date", "expected_date", "notes", "lines", "totals", "created_at"]
        read_only_fields = ["number", "status"]

    def get_totals(self, obj):
        return services.totals(obj)

    def validate_lines(self, lines):
        if not lines:
            raise serializers.ValidationError("Add at least one item.")
        return lines

    def _write_lines(self, po, lines):
        for ln in lines:
            src = SupplierItem.objects.filter(supplier=po.supplier, item=ln["item"]).first()
            for f in ("pack_name", "pack_qty", "price_per_pack"):
                if ln.get(f) in (None, ""):
                    if src is None:
                        raise serializers.ValidationError(
                            {"lines": f"{po.supplier} has no price for {ln['item'].code}; enter pack and price."})
                    ln[f] = getattr(src, f)
            PurchaseOrderLine.objects.create(order=po, **ln)

    @transaction.atomic
    def create(self, data):
        lines = data.pop("lines")
        po = PurchaseOrder.objects.create(created_by=self.context["request"].user, **data)
        self._write_lines(po, lines)
        return po

    @transaction.atomic
    def update(self, po, data):
        if po.status != PurchaseOrder.Status.DRAFT:
            raise serializers.ValidationError({"detail": "Only draft orders can be changed."})
        lines = data.pop("lines", None)
        for k, v in data.items():
            setattr(po, k, v)
        po.save()
        if lines is not None:
            po.lines.all().delete()
            self._write_lines(po, lines)
        return po


class ReceiveSerializer(serializers.Serializer):
    line = serializers.IntegerField()
    packs = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    location = serializers.SlugRelatedField(slug_field="code", queryset=Location.objects.all())
    lot_code = serializers.CharField(required=False, allow_blank=True, default="")
    colour_ref = serializers.CharField(required=False, allow_blank=True, default="")
    supplier_batch = serializers.CharField(required=False, allow_blank=True, default="")


class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.prefetch_related("items__item__base_uom")
    serializer_class = SupplierSerializer
    pagination_class = None


class SupplierItemViewSet(viewsets.ModelViewSet):
    queryset = SupplierItem.objects.select_related("supplier", "item__base_uom")
    serializer_class = SupplierItemSerializer
    pagination_class = None

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("supplier"):
            qs = qs.filter(supplier_id=p["supplier"])
        if p.get("item"):
            qs = qs.filter(item__code=p["item"])
        return qs


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.select_related("supplier").prefetch_related("lines__item__base_uom")
    serializer_class = OrderSerializer
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status__in=p["status"].split(","))
        if p.get("supplier"):
            qs = qs.filter(supplier_id=p["supplier"])
        return qs

    def _move(self, po, allowed, to):
        if po.status not in allowed:
            raise serializers.ValidationError({"detail": f"{po.number} is {po.get_status_display().lower()}."})
        po.status = to
        po.save(update_fields=["status"])
        return Response(self.get_serializer(po).data)

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        """Mark a draft as sent to the supplier. From then on it can be received."""
        S = PurchaseOrder.Status
        return self._move(self.get_object(), [S.DRAFT], S.SENT)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        S = PurchaseOrder.Status
        po = self.get_object()
        if po.lines.filter(received_packs__gt=0).exists():
            raise serializers.ValidationError({"detail": "Goods were already received on this order; it cannot be cancelled."})
        return self._move(po, [S.DRAFT, S.SENT], S.CANCELLED)

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        po = self.get_object()
        s = ReceiveSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        line = po.lines.filter(pk=d.pop("line")).first()
        if line is None:
            raise serializers.ValidationError({"line": f"No such line on {po.number}."})
        services.receive_line(line, user=request.user, **d)
        po.refresh_from_db()
        return Response(self.get_serializer(po).data)


class ShortagesView(APIView):
    def get(self, request):
        return Response(services.shortages())


class DraftOrdersView(APIView):
    """Create one draft purchase order per supplier from the current shortages."""

    def post(self, request):
        items = request.data.get("items") or None
        orders = services.draft_orders(user=request.user, items=set(items) if items else None)
        return Response([{"id": po.id, "number": po.number, "supplier": po.supplier.name,
                          "lines": po.lines.count()} for po in orders], status=status.HTTP_201_CREATED)
