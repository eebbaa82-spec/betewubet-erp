from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.catalog.models import ProductTemplate

from . import services
from .models import Customer, SalesOrder, SalesOrderLine


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = "__all__"


class LineSerializer(serializers.ModelSerializer):
    template_name = serializers.CharField(source="template.name", read_only=True)
    template_code = serializers.SlugRelatedField(source="template", slug_field="code",
                                                 queryset=ProductTemplate.objects.filter(is_sellable=True))
    line_total = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)

    class Meta:
        model = SalesOrderLine
        fields = ["id", "order", "sequence", "template_code", "template_name", "configuration", "description", "quantity",
                  "estimated_unit_cost", "unit_price", "price_locked", "line_total", "estimate"]
        read_only_fields = ["estimated_unit_cost", "estimate"]

    def validate(self, attrs):
        order = attrs.get("order") or (self.instance and self.instance.order)
        if order and order.status != SalesOrder.Status.QUOTE:
            raise serializers.ValidationError(f"{order.number} is confirmed; its lines can no longer change.")
        return attrs

    def save(self, **kwargs):
        line = super().save(**kwargs)
        return services.price_line(line)


class OrderSerializer(serializers.ModelSerializer):
    lines = LineSerializer(many=True, read_only=True)
    totals = serializers.SerializerMethodField()
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = SalesOrder
        fields = "__all__"
        read_only_fields = ["number", "status"]

    def get_totals(self, obj):
        return services.totals(obj)


class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer


class SalesOrderViewSet(viewsets.ModelViewSet):
    queryset = SalesOrder.objects.select_related("customer").prefetch_related("lines__template")
    serializer_class = OrderSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        st = self.request.query_params.get("status")
        return qs.filter(status=st) if st else qs

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        order = self.get_object()
        work_orders = services.confirm(order)
        return Response({"order": order.number, "status": order.status,
                         "work_orders": [wo.number for wo in work_orders]})


class SalesOrderLineViewSet(viewsets.ModelViewSet):
    queryset = SalesOrderLine.objects.select_related("template", "order")
    serializer_class = LineSerializer

    def perform_destroy(self, instance):
        if instance.order.status != SalesOrder.Status.QUOTE:
            raise serializers.ValidationError(f"{instance.order.number} is confirmed; its lines can no longer change.")
        instance.delete()
