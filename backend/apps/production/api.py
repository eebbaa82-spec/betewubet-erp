from decimal import Decimal

from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from . import costing, services
from .models import WorkOrder, WorkOrderMaterial, WorkOrderOperation


class MaterialSerializer(serializers.ModelSerializer):
    item = serializers.SlugRelatedField(slug_field="code", read_only=True)

    class Meta:
        model = WorkOrderMaterial
        fields = ["item", "planned_qty"]


class OperationSerializer(serializers.ModelSerializer):
    work_center = serializers.SlugRelatedField(slug_field="code", read_only=True)
    work_order = serializers.SlugRelatedField(slug_field="number", read_only=True)

    class Meta:
        model = WorkOrderOperation
        fields = ["id", "work_order", "sequence", "work_center", "description", "planned_minutes", "status"]


class WorkOrderSerializer(serializers.ModelSerializer):
    template = serializers.SlugRelatedField(slug_field="code", read_only=True)
    materials = MaterialSerializer(many=True, read_only=True)
    operations = OperationSerializer(many=True, read_only=True)

    class Meta:
        model = WorkOrder
        fields = ["id", "number", "template", "configuration", "quantity", "status", "due_date", "sales_line",
                  "estimate", "materials", "operations", "exploded"]


class StopRequest(serializers.Serializer):
    good_qty = serializers.DecimalField(max_digits=10, decimal_places=2, default=Decimal(0), min_value=Decimal(0))
    rejected_qty = serializers.DecimalField(max_digits=10, decimal_places=2, default=Decimal(0), min_value=Decimal(0))
    reject_reason = serializers.CharField(required=False, allow_blank=True, default="")
    finished = serializers.BooleanField(default=False)


class WorkOrderViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = WorkOrder.objects.select_related("template").prefetch_related("materials__item", "operations")
    serializer_class = WorkOrderSerializer

    @action(detail=True)
    def cost(self, request, pk=None):
        """Estimated vs actual cost so far, line by line."""
        return Response(costing.variance(self.get_object()))


class OperationViewSet(viewsets.ReadOnlyModelViewSet):
    """What a station tablet uses: list queued operations at a work center, start and stop them."""

    serializer_class = OperationSerializer

    def get_queryset(self):
        qs = WorkOrderOperation.objects.select_related("work_center", "work_order")
        wc = self.request.query_params.get("work_center")
        return qs.filter(work_center__code=wc) if wc else qs

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        log = services.start_operation(self.get_object(), operator=request.user)
        return Response({"started_at": log.started_at})

    @action(detail=True, methods=["post"])
    def stop(self, request, pk=None):
        req = StopRequest(data=request.data)
        req.is_valid(raise_exception=True)
        log = services.stop_operation(self.get_object(), **req.validated_data)
        return Response({"minutes": str(log.minutes) if log else "0"})
