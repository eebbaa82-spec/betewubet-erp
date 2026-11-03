from datetime import date
from decimal import Decimal

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.sales.models import SalesOrder, SalesOrderLine

from . import services
from .models import Delivery, Installation


class DeliveryLineSerializer(serializers.Serializer):
    line = serializers.IntegerField(source="sales_line_id")
    sequence = serializers.IntegerField(source="sales_line.sequence")
    product = serializers.CharField(source="sales_line.template.name")
    description = serializers.CharField(source="sales_line.description")
    configuration = serializers.JSONField(source="sales_line.configuration")
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)


class InstallationSerializer(serializers.ModelSerializer):
    delivery = serializers.SlugRelatedField(slug_field="number", read_only=True)
    order_number = serializers.CharField(source="delivery.order.number", read_only=True)
    customer = serializers.CharField(source="delivery.order.customer.name", read_only=True)
    address = serializers.CharField(source="delivery.address", read_only=True)
    contact_phone = serializers.CharField(source="delivery.contact_phone", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    return_visit_of = serializers.SlugRelatedField(slug_field="number", read_only=True)

    class Meta:
        model = Installation
        fields = ["id", "number", "delivery", "order_number", "customer", "address", "contact_phone", "status",
                  "status_label", "scheduled_date", "crew", "completed_at", "signed_off_by", "snags", "notes",
                  "return_visit_of"]
        read_only_fields = ["number", "status", "completed_at", "signed_off_by", "snags"]


class DeliverySerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.number", read_only=True)
    order_id = serializers.IntegerField(source="order.id", read_only=True)
    customer = serializers.CharField(source="order.customer.name", read_only=True)
    customer_tin = serializers.CharField(source="order.customer.tin", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    lines = DeliveryLineSerializer(many=True, read_only=True)
    installations = InstallationSerializer(many=True, read_only=True)

    class Meta:
        model = Delivery
        fields = ["id", "number", "order_id", "order_number", "customer", "customer_tin", "status", "status_label",
                  "scheduled_date", "vehicle", "driver", "address", "contact_phone", "install_required", "notes",
                  "dispatched_at", "delivered_at", "received_by", "lines", "installations", "created_at"]
        read_only_fields = ["number", "status", "dispatched_at", "delivered_at", "received_by"]


class NewLine(serializers.Serializer):
    line = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal(0))


class NewDelivery(serializers.Serializer):
    order = serializers.PrimaryKeyRelatedField(queryset=SalesOrder.objects.all())
    scheduled_date = serializers.DateField(default=date.today)
    vehicle = serializers.CharField(required=False, allow_blank=True, default="")
    driver = serializers.CharField(required=False, allow_blank=True, default="")
    address = serializers.CharField(required=False, allow_blank=True)
    contact_phone = serializers.CharField(required=False, allow_blank=True)
    install_required = serializers.BooleanField(default=False)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    lines = NewLine(many=True)


class DeliverRequest(serializers.Serializer):
    received_by = serializers.CharField()
    install_date = serializers.DateField(required=False, allow_null=True, default=None)
    crew = serializers.CharField(required=False, allow_blank=True, default="")


class CompleteRequest(serializers.Serializer):
    signed_off_by = serializers.CharField()
    snags = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    return_date = serializers.DateField(required=False, allow_null=True, default=None)


class DeliveryViewSet(viewsets.ModelViewSet):
    queryset = Delivery.objects.select_related("order__customer").prefetch_related(
        "lines__sales_line__template", "installations__delivery__order__customer", "installations__return_visit_of")
    serializer_class = DeliverySerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status__in=p["status"].split(","))
        if p.get("order"):
            qs = qs.filter(order_id=p["order"])
        return qs

    def create(self, request, *args, **kwargs):
        req = NewDelivery(data=request.data)
        req.is_valid(raise_exception=True)
        d = dict(req.validated_data)
        order = d.pop("order")
        wanted = d.pop("lines")
        lines = {l.id: l for l in SalesOrderLine.objects.filter(id__in=[w["line"] for w in wanted]).select_related("template")}
        missing = [w["line"] for w in wanted if w["line"] not in lines]
        if missing:
            raise serializers.ValidationError({"lines": f"No order line {missing[0]}."})
        delivery = services.create_delivery(order, [(lines[w["line"]], w["quantity"]) for w in wanted],
                                            user=request.user, **d)
        return Response(self.get_serializer(self.get_queryset().get(pk=delivery.pk)).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        if self.get_object().status != Delivery.Status.PLANNED:
            raise serializers.ValidationError({"detail": "Only planned deliveries can be changed."})
        return super().partial_update(request, *args, **kwargs)

    def _done(self, d):
        return Response(self.get_serializer(self.get_queryset().get(pk=d.pk)).data)

    @action(detail=True, methods=["post"], url_path="dispatch")
    def send_out(self, request, pk=None):  # not named "dispatch": that is the view's own request handler
        """The truck has left the factory."""
        return self._done(services.dispatch(self.get_object()))

    @action(detail=True, methods=["post"])
    def deliver(self, request, pk=None):
        """Proof of delivery: who received it. Creates the installation visit when one is needed."""
        req = DeliverRequest(data=request.data)
        req.is_valid(raise_exception=True)
        return self._done(services.deliver(self.get_object(), **req.validated_data))

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._done(services.cancel(self.get_object()))


class InstallationViewSet(viewsets.ModelViewSet):
    queryset = Installation.objects.select_related("delivery__order__customer", "return_visit_of")
    serializer_class = InstallationSerializer
    http_method_names = ["get", "patch", "head", "options", "post"]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get("status"):
            qs = qs.filter(status__in=self.request.query_params["status"].split(","))
        return qs

    def create(self, request, *args, **kwargs):
        raise serializers.ValidationError({"detail": "Installations are created when a delivery is marked delivered."})

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        req = CompleteRequest(data=request.data)
        req.is_valid(raise_exception=True)
        job, follow_up = services.complete_installation(self.get_object(), **req.validated_data)
        data = self.get_serializer(job).data
        data["follow_up"] = self.get_serializer(follow_up).data if follow_up else None
        return Response(data)


class ReadyView(APIView):
    def get(self, request):
        return Response(services.ready_to_ship())
