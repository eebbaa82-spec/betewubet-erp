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
    queryset = Offcut.objects.select_related("item", "location")
    serializer_class = OffcutSerializer
