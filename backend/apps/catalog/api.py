from decimal import Decimal

from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.inventory.services import match_offcuts, on_hand
from apps.production import costing

from .explode import explode
from .models import BOMLine, Item, ProductTemplate, RoutingStep, TemplateParameter


class ItemSerializer(serializers.ModelSerializer):
    base_uom = serializers.SlugRelatedField(slug_field="code", read_only=True)

    class Meta:
        model = Item
        fields = ["id", "code", "name", "kind", "base_uom", "standard_cost", "thickness_mm",
                  "sheet_length_mm", "sheet_width_mm", "track_lots", "reorder_level", "lead_time_days", "active"]


class ParameterSerializer(serializers.ModelSerializer):
    class Meta:
        model = TemplateParameter
        fields = ["name", "label", "kind", "default", "min_value", "max_value", "choices", "item_kind"]


class BOMLineSerializer(serializers.ModelSerializer):
    item = serializers.SlugRelatedField(slug_field="code", read_only=True)
    edge_item = serializers.SlugRelatedField(slug_field="code", read_only=True)
    child_template = serializers.SlugRelatedField(slug_field="code", read_only=True)

    class Meta:
        model = BOMLine
        exclude = ["template"]


class RoutingSerializer(serializers.ModelSerializer):
    work_center = serializers.SlugRelatedField(slug_field="code", read_only=True)

    class Meta:
        model = RoutingStep
        exclude = ["template"]


class TemplateSerializer(serializers.ModelSerializer):
    parameters = ParameterSerializer(many=True, read_only=True)
    bom_lines = BOMLineSerializer(many=True, read_only=True)
    routing = RoutingSerializer(many=True, read_only=True)

    class Meta:
        model = ProductTemplate
        fields = ["id", "code", "name", "description", "is_sellable", "active", "parameters", "bom_lines", "routing"]


class ExplodeRequest(serializers.Serializer):
    params = serializers.DictField(required=False, default=dict)
    qty = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, default=Decimal("1"), min_value=Decimal("0.01"))


class ItemViewSet(viewsets.ModelViewSet):
    queryset = Item.objects.select_related("base_uom")
    serializer_class = ItemSerializer

    @action(detail=True)
    def stock(self, request, pk=None):
        item = self.get_object()
        return Response({"item": item.code, "on_hand": str(on_hand(item)), "uom": item.base_uom.code})


class ProductTemplateViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProductTemplate.objects.prefetch_related("parameters", "bom_lines", "routing")
    serializer_class = TemplateSerializer
    lookup_field = "code"

    @action(detail=True, methods=["post"])
    def explode(self, request, code=None):
        """Configure a product: returns parts, hardware, routing, cost estimate and
        which parts can be cut from offcuts in stock."""
        req = ExplodeRequest(data=request.data)
        req.is_valid(raise_exception=True)
        result = explode(self.get_object(), req.validated_data["params"], qty=req.validated_data["qty"])
        matches = match_offcuts(result.panels)
        return Response({
            **result.to_dict(),
            "estimate": costing.estimate(result),
            "offcut_matches": [
                {"panel": result.panels[i].name, "path": result.panels[i].path, "offcut": o.code,
                 "offcut_size_mm": [o.length_mm, o.width_mm]}
                for i, o in matches
            ],
        })
