from decimal import Decimal

from rest_framework import serializers, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.production.models import WorkOrder, WorkOrderOperation

from . import services
from .models import Checklist, ChecklistItem, Inspection, InspectionResult


class ItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChecklistItem
        fields = ["id", "sequence", "text", "kind", "target", "tolerance"]


class ChecklistSerializer(serializers.ModelSerializer):
    work_center = serializers.SlugRelatedField(slug_field="code", read_only=True)
    items = ItemSerializer(many=True, read_only=True)

    class Meta:
        model = Checklist
        fields = ["id", "name", "stage", "work_center", "items"]


class ResultSerializer(serializers.ModelSerializer):
    text = serializers.CharField(source="item.text", read_only=True)

    class Meta:
        model = InspectionResult
        fields = ["item", "text", "passed", "value", "note"]


class InspectionSerializer(serializers.ModelSerializer):
    work_order = serializers.SlugRelatedField(slug_field="number", read_only=True)
    work_order_id = serializers.IntegerField(read_only=True)
    product = serializers.CharField(source="work_order.template.name", read_only=True)
    customer = serializers.CharField(source="work_order.sales_line.order.customer.name", read_only=True, default="")
    checklist_name = serializers.CharField(source="checklist.name", read_only=True)
    stage = serializers.CharField(source="checklist.stage", read_only=True)
    work_center = serializers.CharField(source="operation.work_center.code", read_only=True, default="")
    result_label = serializers.CharField(source="get_result_display", read_only=True)
    non_conformance = serializers.SlugRelatedField(slug_field="number", read_only=True)
    rework_order = serializers.CharField(source="non_conformance.rework_order.number", read_only=True, default=None)
    inspector = serializers.SerializerMethodField()
    results = ResultSerializer(many=True, read_only=True)

    class Meta:
        model = Inspection
        fields = ["id", "number", "work_order", "work_order_id", "product", "customer", "checklist", "checklist_name",
                  "stage", "work_center", "result", "result_label", "failed_qty", "notes", "non_conformance",
                  "rework_order", "inspector", "created_at", "results"]

    def get_inspector(self, obj):
        u = obj.inspector
        return (u.get_full_name() or u.username) if u else ""


class Answer(serializers.Serializer):
    item = serializers.IntegerField()
    passed = serializers.BooleanField(required=False, allow_null=True, default=None)
    value = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True, default=None)
    note = serializers.CharField(required=False, allow_blank=True, default="")


class NewInspection(serializers.Serializer):
    work_order = serializers.PrimaryKeyRelatedField(queryset=WorkOrder.objects.all())
    checklist = serializers.PrimaryKeyRelatedField(queryset=Checklist.objects.filter(active=True))
    operation = serializers.PrimaryKeyRelatedField(queryset=WorkOrderOperation.objects.all(), required=False,
                                                   allow_null=True, default=None)
    answers = Answer(many=True)
    failed_qty = serializers.DecimalField(max_digits=10, decimal_places=2, default=Decimal(0), min_value=Decimal(0))
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class ChecklistViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Checklist.objects.filter(active=True).select_related("work_center").prefetch_related("items")
    serializer_class = ChecklistSerializer
    pagination_class = None

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("work_center"):
            qs = qs.filter(work_center__code=p["work_center"])
        if p.get("stage"):
            qs = qs.filter(stage=p["stage"])
        return qs


class InspectionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Inspection.objects.select_related(
        "work_order__template", "work_order__sales_line__order__customer", "checklist", "operation__work_center",
        "non_conformance__rework_order", "inspector").prefetch_related("results__item")
    serializer_class = InspectionSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("work_order"):
            qs = qs.filter(work_order_id=p["work_order"])
        if p.get("result"):
            qs = qs.filter(result=p["result"])
        if p.get("stage"):
            qs = qs.filter(checklist__stage=p["stage"])
        return qs

    def create(self, request, *args, **kwargs):
        req = NewInspection(data=request.data)
        req.is_valid(raise_exception=True)
        d = req.validated_data
        answers = {a["item"]: a for a in d["answers"]}
        insp = services.record(d["work_order"], d["checklist"], answers, operation=d["operation"],
                              failed_qty=d["failed_qty"], notes=d["notes"], user=request.user)
        return Response(self.get_serializer(self.get_queryset().get(pk=insp.pk)).data, status=status.HTTP_201_CREATED)


class AwaitingFinalView(APIView):
    """Finished jobs that still need to pass final inspection before they can ship."""

    def get(self, request):
        if services.final_checklist() is None:
            return Response([])
        rows = []
        for wo in WorkOrder.objects.filter(status="done", rework_of__isnull=True).select_related(
                "template", "sales_line__order__customer").order_by("due_date", "id"):
            if not services.passed_final(wo):
                last = wo.inspections.filter(checklist__stage="final").first()
                rows.append({"id": wo.id, "number": wo.number, "product": wo.template.name,
                             "configuration": wo.configuration, "quantity": str(wo.quantity),
                             "order_number": wo.sales_line.order.number if wo.sales_line else "",
                             "customer": wo.sales_line.order.customer.name if wo.sales_line else "",
                             "due_date": wo.due_date, "last_result": last.result if last else None})
        return Response(rows)
