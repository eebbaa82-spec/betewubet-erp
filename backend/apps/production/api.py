from decimal import Decimal

from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from django.http import HttpResponse

from . import costing, cutlist, scanning, services
from django.db.models import Sum
from django.utils import timezone

from apps.core.models import WorkCenter
from apps.inventory.models import StockMove

from .models import NonConformance, WorkOrder, WorkOrderMaterial, WorkOrderOperation


class WorkCenterSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkCenter
        fields = ["code", "name", "machine_rate", "labour_rate"]


class MaterialSerializer(serializers.ModelSerializer):
    item = serializers.SlugRelatedField(slug_field="code", read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)
    uom = serializers.CharField(source="item.base_uom.code", read_only=True)
    issued_qty = serializers.SerializerMethodField()

    class Meta:
        model = WorkOrderMaterial
        fields = ["item", "item_name", "uom", "planned_qty", "issued_qty"]

    def get_issued_qty(self, obj):
        total = StockMove.objects.filter(work_order=obj.work_order, item=obj.item).exclude(
            kind=StockMove.Kind.OFFCUT).aggregate(t=Sum("qty"))["t"]
        return str(-(total or 0))


class OperationSerializer(serializers.ModelSerializer):
    work_center = serializers.SlugRelatedField(slug_field="code", read_only=True)
    work_order = serializers.SlugRelatedField(slug_field="number", read_only=True)
    work_order_id = serializers.IntegerField(source="work_order.id", read_only=True)
    product = serializers.CharField(source="work_order.template.name", read_only=True)
    quantity = serializers.DecimalField(source="work_order.quantity", max_digits=10, decimal_places=2, read_only=True)
    order_number = serializers.CharField(source="work_order.sales_line.order.number", read_only=True, default="")
    customer = serializers.CharField(source="work_order.sales_line.order.customer.name", read_only=True, default="")
    is_rework = serializers.SerializerMethodField()
    spent_minutes = serializers.SerializerMethodField()
    running_since = serializers.SerializerMethodField()
    pieces_total = serializers.SerializerMethodField()
    pieces_scanned = serializers.SerializerMethodField()

    class Meta:
        model = WorkOrderOperation
        fields = ["id", "work_order", "work_order_id", "sequence", "work_center", "description", "planned_minutes",
                  "status", "product", "quantity", "order_number", "customer", "is_rework", "spent_minutes",
                  "running_since", "pieces_total", "pieces_scanned"]

    def get_is_rework(self, obj):
        return obj.work_order.rework_of_id is not None

    def get_spent_minutes(self, obj):
        return str(sum((t.minutes for t in obj.time_logs.all()), Decimal(0)))

    def get_pieces_total(self, obj):
        return sum(scanning.pieces_for(obj).values())

    def get_pieces_scanned(self, obj):
        return len(obj.part_scans.all())

    def get_running_since(self, obj):
        open_log = next((t for t in obj.time_logs.all() if t.ended_at is None), None)
        return open_log.started_at if open_log else None


class NonConformanceSerializer(serializers.ModelSerializer):
    work_order = serializers.SlugRelatedField(slug_field="number", read_only=True)
    rework_order = serializers.SlugRelatedField(slug_field="number", read_only=True)
    work_center = serializers.CharField(source="operation.work_center.code", read_only=True)

    class Meta:
        model = NonConformance
        fields = ["number", "work_order", "work_center", "qty", "reason", "rework_order", "created_at"]


class WorkOrderSerializer(serializers.ModelSerializer):
    template = serializers.SlugRelatedField(slug_field="code", read_only=True)
    product = serializers.CharField(source="template.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    order_number = serializers.CharField(source="sales_line.order.number", read_only=True, default="")
    order_id = serializers.IntegerField(source="sales_line.order.id", read_only=True, default=None)
    customer = serializers.CharField(source="sales_line.order.customer.name", read_only=True, default="")
    rework_of = serializers.SlugRelatedField(slug_field="number", read_only=True)
    materials = MaterialSerializer(many=True, read_only=True)
    operations = OperationSerializer(many=True, read_only=True)
    non_conformances = NonConformanceSerializer(many=True, read_only=True)

    class Meta:
        model = WorkOrder
        fields = ["id", "number", "template", "product", "configuration", "quantity", "status", "status_label",
                  "due_date", "sales_line", "order_number", "order_id", "customer", "rework_of", "estimate",
                  "materials", "operations", "non_conformances", "created_at"]


class StopRequest(serializers.Serializer):
    good_qty = serializers.DecimalField(max_digits=10, decimal_places=2, default=Decimal(0), min_value=Decimal(0))
    rejected_qty = serializers.DecimalField(max_digits=10, decimal_places=2, default=Decimal(0), min_value=Decimal(0))
    reject_reason = serializers.CharField(required=False, allow_blank=True, default="")
    finished = serializers.BooleanField(default=False)


class ScanRequest(serializers.Serializer):
    code = serializers.CharField(max_length=40)


class WorkCenterViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = WorkCenter.objects.all()
    serializer_class = WorkCenterSerializer
    lookup_field = "code"
    pagination_class = None

    @action(detail=True, methods=["post"])
    def scan(self, request, code=None):
        """A job or panel label scanned at this station: starts the step and records the piece."""
        req = ScanRequest(data=request.data)
        req.is_valid(raise_exception=True)
        return Response(scanning.scan(self.get_object(), req.validated_data["code"], user=request.user))


class WorkOrderViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = WorkOrder.objects.select_related(
        "template", "rework_of", "sales_line__order__customer"
    ).prefetch_related("materials__item__base_uom", "operations__work_center", "operations__time_logs", "operations__part_scans",
                       "non_conformances__operation__work_center", "non_conformances__rework_order")
    serializer_class = WorkOrderSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status__in=p["status"].split(","))
        if p.get("number"):
            qs = qs.filter(number=p["number"].strip().upper())
        return qs

    @action(detail=True)
    def cost(self, request, pk=None):
        """Estimated vs actual cost so far, line by line."""
        return Response(costing.variance(self.get_object()))

    @action(detail=True, url_path="cut-list")
    def cut_list(self, request, pk=None):
        """Panels to cut, grouped by board, with part IDs for labels."""
        return Response(cutlist.cut_list(self.get_object()))

    @action(detail=True, url_path="cut-list/csv")
    def cut_list_csv(self, request, pk=None):
        """The same cut list as a CSV file for nesting software."""
        wo = self.get_object()
        resp = HttpResponse(cutlist.to_csv(cutlist.cut_list(wo)), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{wo.number}-cut-list.csv"'
        return resp


class OperationViewSet(viewsets.ReadOnlyModelViewSet):
    """What a station tablet uses: list queued operations at a work center, start and stop them."""

    serializer_class = OperationSerializer

    def get_queryset(self):
        qs = WorkOrderOperation.objects.select_related(
            "work_center", "work_order__template", "work_order__sales_line__order__customer"
        ).prefetch_related("time_logs", "part_scans", "work_order__operations").exclude(
            work_order__status__in=["done", "cancelled"])
        p = self.request.query_params
        if p.get("work_center"):
            qs = qs.filter(work_center__code=p["work_center"])
        if p.get("open"):
            qs = qs.exclude(status=WorkOrderOperation.Status.DONE)
        return qs.order_by("work_order__due_date", "work_order__id", "sequence")

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        op = self.get_object()
        if op.status == WorkOrderOperation.Status.DONE:
            raise serializers.ValidationError({"detail": "This step is already finished."})
        from apps.maintenance.services import down_reason
        down = down_reason(op.work_center)
        if down:
            raise serializers.ValidationError({"detail": down})
        busy = WorkOrderOperation.objects.filter(
            work_center=op.work_center, status=WorkOrderOperation.Status.RUNNING).exclude(pk=op.pk).first()
        if busy:
            raise serializers.ValidationError({"detail": f"{busy.work_order.number} is still running here. Pause or finish it first."})
        log = services.start_operation(op, operator=request.user)
        return Response({"started_at": log.started_at})

    @action(detail=True, methods=["post"])
    def stop(self, request, pk=None):
        req = StopRequest(data=request.data)
        req.is_valid(raise_exception=True)
        op = self.get_object()
        if req.validated_data["rejected_qty"] > 0 and not req.validated_data["reject_reason"]:
            raise serializers.ValidationError({"reject_reason": "Say why the parts were rejected."})
        log = services.stop_operation(op, operator=request.user, **req.validated_data)
        ncr = op.non_conformances.order_by("-id").first() if req.validated_data["rejected_qty"] > 0 else None
        return Response({
            "minutes": str(log.minutes) if log else "0",
            "non_conformance": ncr.number if ncr else None,
            "rework_order": ncr.rework_order.number if ncr and ncr.rework_order else None,
        })


class NonConformanceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = NonConformance.objects.select_related("work_order", "rework_order", "operation__work_center")
    serializer_class = NonConformanceSerializer
