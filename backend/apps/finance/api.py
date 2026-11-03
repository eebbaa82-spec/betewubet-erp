from datetime import date
from decimal import Decimal

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.dispatch.models import Delivery
from apps.purchasing.models import PurchaseOrder, Supplier
from apps.sales.models import SalesOrder

from . import services
from .models import FinanceSettings, Invoice, InvoiceLine, Payment, PaymentMethod, SupplierBill, SupplierPayment

money = dict(max_digits=14, decimal_places=2)


class LineSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(read_only=True, **money)
    advance = serializers.SlugRelatedField(slug_field="number", read_only=True)

    class Meta:
        model = InvoiceLine
        fields = ["id", "sequence", "description", "quantity", "unit_price", "amount", "advance"]


class PaymentSerializer(serializers.ModelSerializer):
    method_label = serializers.CharField(source="get_method_display", read_only=True)

    class Meta:
        model = Payment
        fields = ["id", "number", "date", "amount", "withholding", "withholding_receipt_no", "method",
                  "method_label", "reference"]


class InvoiceSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", read_only=True)
    customer_tin = serializers.CharField(source="customer.tin", read_only=True)
    customer_vat_no = serializers.CharField(source="customer.vat_reg_no", read_only=True)
    customer_address = serializers.CharField(source="customer.address", read_only=True)
    order_number = serializers.CharField(source="order.number", read_only=True, default="")
    delivery_number = serializers.CharField(source="delivery.number", read_only=True, default="")
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    subtotal = serializers.DecimalField(read_only=True, **money)
    vat = serializers.DecimalField(read_only=True, **money)
    total = serializers.DecimalField(read_only=True, **money)
    paid = serializers.DecimalField(read_only=True, **money)
    balance = serializers.DecimalField(read_only=True, **money)
    expected_withholding = serializers.SerializerMethodField()
    payment_status = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = ["id", "number", "kind", "kind_label", "status", "payment_status", "customer", "customer_name",
                  "customer_tin", "customer_vat_no", "customer_address", "order", "order_number", "delivery",
                  "delivery_number", "issue_date", "due_date", "fiscal_receipt_no", "vat_rate", "notes",
                  "subtotal", "vat", "total", "paid", "balance", "expected_withholding", "created_at"]
        read_only_fields = ["number", "kind", "status", "customer", "order", "delivery", "issue_date", "due_date",
                            "vat_rate"]

    def get_expected_withholding(self, obj):
        return str(services.expected_withholding(obj))

    def get_payment_status(self, obj):
        if obj.status == Invoice.Status.DRAFT:
            return "draft"
        if obj.balance <= Decimal("0.005"):
            return "paid"
        if obj.due_date and obj.due_date < date.today():
            return "overdue"
        return "part_paid" if obj.paid > 0 else "unpaid"


class InvoiceDetailSerializer(InvoiceSerializer):
    lines = LineSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)

    class Meta(InvoiceSerializer.Meta):
        fields = InvoiceSerializer.Meta.fields + ["lines", "payments"]


class NewInvoice(serializers.Serializer):
    delivery = serializers.PrimaryKeyRelatedField(queryset=Delivery.objects.all(), required=False)
    advance_for = serializers.PrimaryKeyRelatedField(queryset=SalesOrder.objects.all(), required=False)
    advance_pct = serializers.DecimalField(max_digits=5, decimal_places=4, required=False)

    def validate(self, d):
        if bool(d.get("delivery")) == bool(d.get("advance_for")):
            raise serializers.ValidationError("Give either a delivery note or an order for an advance invoice.")
        return d


class IssueRequest(serializers.Serializer):
    issue_date = serializers.DateField(required=False, allow_null=True)
    fiscal_receipt_no = serializers.CharField(required=False, allow_blank=True, default="")


class PaymentRequest(serializers.Serializer):
    amount = serializers.DecimalField(**money)
    withholding = serializers.DecimalField(default=Decimal(0), **money)
    withholding_receipt_no = serializers.CharField(required=False, allow_blank=True, default="")
    date = serializers.DateField(required=False, allow_null=True)
    method = serializers.ChoiceField(choices=PaymentMethod.choices, default=PaymentMethod.BANK)
    reference = serializers.CharField(required=False, allow_blank=True, default="")


class InvoiceViewSet(viewsets.ModelViewSet):
    queryset = Invoice.objects.select_related("customer", "order", "delivery").prefetch_related(
        "lines__advance", "payments")
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_serializer_class(self):
        return InvoiceSerializer if self.action == "list" else InvoiceDetailSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("customer"):
            qs = qs.filter(customer_id=p["customer"])
        if p.get("order"):
            qs = qs.filter(order_id=p["order"])
        return qs

    def _out(self, inv, code=status.HTTP_200_OK):
        return Response(InvoiceDetailSerializer(self.get_queryset().get(pk=inv.pk)).data, status=code)

    def create(self, request, *args, **kwargs):
        req = NewInvoice(data=request.data)
        req.is_valid(raise_exception=True)
        d = req.validated_data
        if d.get("delivery"):
            inv = services.invoice_delivery(d["delivery"], user=request.user)
        else:
            inv = services.advance_invoice(d["advance_for"], d.get("advance_pct"), user=request.user)
        return self._out(inv, status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        inv = self.get_object()
        data = {k: v for k, v in request.data.items() if k in ("notes", "fiscal_receipt_no")}
        ser = InvoiceDetailSerializer(inv, data=data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return self._out(inv)

    def destroy(self, request, *args, **kwargs):
        inv = self.get_object()
        if inv.status != Invoice.Status.DRAFT:
            raise serializers.ValidationError({"detail": "An issued invoice cannot be deleted."})
        inv.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def issue(self, request, pk=None):
        req = IssueRequest(data=request.data)
        req.is_valid(raise_exception=True)
        return self._out(services.issue(self.get_object(), **req.validated_data))

    @action(detail=True, methods=["post"])
    def payments(self, request, pk=None):
        req = PaymentRequest(data=request.data)
        req.is_valid(raise_exception=True)
        d = dict(req.validated_data)
        services.record_payment(self.get_object(), d.pop("amount"), d.pop("withholding"), on=d.pop("date", None),
                                user=request.user, **d)
        return self._out(self.get_object(), status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="lines")
    def add_line(self, request, pk=None):
        """Add a hand-written line (delivery charge, installation) to a draft."""
        inv = self.get_object()
        if inv.status != Invoice.Status.DRAFT:
            raise serializers.ValidationError({"detail": "Only a draft invoice can be changed."})
        ser = LineSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        last = inv.lines.order_by("-sequence").first()
        ser.save(invoice=inv, sequence=(last.sequence if last else 0) + 10)
        return self._out(inv, status.HTTP_201_CREATED)


class SupplierPaymentSerializer(serializers.ModelSerializer):
    method_label = serializers.CharField(source="get_method_display", read_only=True)

    class Meta:
        model = SupplierPayment
        fields = ["id", "number", "date", "amount", "method", "method_label", "reference"]


class BillSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    supplier_tin = serializers.CharField(source="supplier.tin", read_only=True)
    purchase_order_number = serializers.CharField(source="purchase_order.number", read_only=True, default="")
    total = serializers.DecimalField(read_only=True, **money)
    payable = serializers.DecimalField(read_only=True, **money)
    paid = serializers.DecimalField(read_only=True, **money)
    balance = serializers.DecimalField(read_only=True, **money)
    payments = SupplierPaymentSerializer(many=True, read_only=True)

    class Meta:
        model = SupplierBill
        fields = ["id", "number", "supplier", "supplier_name", "supplier_tin", "purchase_order",
                  "purchase_order_number", "supplier_invoice_no", "bill_date", "due_date", "subtotal", "vat",
                  "withholding", "total", "payable", "paid", "balance", "notes", "payments"]
        read_only_fields = ["number", "due_date", "vat", "withholding"]


class NewBill(serializers.Serializer):
    purchase_order = serializers.PrimaryKeyRelatedField(queryset=PurchaseOrder.objects.all(), required=False)
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.all(), required=False)
    supplier_invoice_no = serializers.CharField()
    bill_date = serializers.DateField(required=False, allow_null=True)
    subtotal = serializers.DecimalField(required=False, allow_null=True, min_value=Decimal("0.01"), **money)
    notes = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, d):
        if not d.get("purchase_order") and not (d.get("supplier") and d.get("subtotal")):
            raise serializers.ValidationError("Choose a purchase order, or a supplier and an amount.")
        return d


class BillPaymentRequest(serializers.Serializer):
    amount = serializers.DecimalField(**money)
    date = serializers.DateField(required=False, allow_null=True)
    method = serializers.ChoiceField(choices=PaymentMethod.choices, default=PaymentMethod.BANK)
    reference = serializers.CharField(required=False, allow_blank=True, default="")


class BillViewSet(viewsets.ModelViewSet):
    queryset = SupplierBill.objects.select_related("supplier", "purchase_order").prefetch_related("payments")
    serializer_class = BillSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get("supplier"):
            qs = qs.filter(supplier_id=self.request.query_params["supplier"])
        return qs

    def create(self, request, *args, **kwargs):
        req = NewBill(data=request.data)
        req.is_valid(raise_exception=True)
        d = req.validated_data
        if d.get("purchase_order"):
            bill = services.bill_from_po(d["purchase_order"], d["supplier_invoice_no"], d.get("bill_date"),
                                         d.get("subtotal"), user=request.user, notes=d["notes"])
        else:
            bill = services.create_bill(d["supplier"], d["supplier_invoice_no"], d["subtotal"], d.get("bill_date"),
                                        user=request.user, notes=d["notes"])
        return Response(self.get_serializer(self.get_queryset().get(pk=bill.pk)).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def payments(self, request, pk=None):
        req = BillPaymentRequest(data=request.data)
        req.is_valid(raise_exception=True)
        d = dict(req.validated_data)
        services.pay_bill(self.get_object(), d.pop("amount"), on=d.pop("date", None), user=request.user, **d)
        return Response(self.get_serializer(self.get_queryset().get(pk=pk)).data, status=status.HTTP_201_CREATED)


class ToInvoiceView(APIView):
    def get(self, request):
        return Response(services.to_invoice())


class ToBillView(APIView):
    def get(self, request):
        return Response(services.to_bill())


class AgingView(APIView):
    def get(self, request, side):
        return Response(services.receivables() if side == "receivables" else services.payables())


class TaxView(APIView):
    def get(self, request):
        today = date.today()
        try:
            year = int(request.query_params.get("year", today.year))
            month = int(request.query_params.get("month", today.month))
            date(year, month, 1)
        except ValueError:
            raise serializers.ValidationError({"detail": "Give a valid year and month."})
        return Response(services.tax_summary(year, month))


class SettingsView(APIView):
    def get(self, request):
        fs = FinanceSettings.current()
        return Response({"company_name": fs.company_name, "company_tin": fs.company_tin,
                         "company_vat_no": fs.company_vat_no, "company_address": fs.company_address,
                         "company_phone": fs.company_phone, "bank_details": fs.bank_details,
                         "withholding_rate": str(fs.withholding_rate),
                         "withholding_threshold": str(fs.withholding_threshold),
                         "payment_terms_days": fs.payment_terms_days, "advance_pct": str(fs.advance_pct)})
