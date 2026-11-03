from decimal import Decimal

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import WorkCenter

from . import services
from .models import Machine, MaintenanceLog, MaintenancePlan


class LogSerializer(serializers.ModelSerializer):
    machine = serializers.SlugRelatedField(slug_field="code", read_only=True)
    machine_name = serializers.CharField(source="machine.name", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    is_open = serializers.BooleanField(read_only=True)
    downtime_minutes = serializers.DecimalField(max_digits=12, decimal_places=0, read_only=True)
    reported_by = serializers.SerializerMethodField()

    class Meta:
        model = MaintenanceLog
        fields = ["id", "machine", "machine_name", "kind", "kind_label", "plan", "description", "machine_down",
                  "reported_at", "reported_by", "closed_at", "action_taken", "done_by", "parts_cost",
                  "machine_hours", "is_open", "downtime_minutes"]

    def get_reported_by(self, obj):
        u = obj.reported_by
        return (u.get_full_name() or u.username) if u else ""


class PlanSerializer(serializers.ModelSerializer):
    machine = serializers.SlugRelatedField(slug_field="code", queryset=Machine.objects.all())

    class Meta:
        model = MaintenancePlan
        fields = ["id", "machine", "task", "instructions", "every_hours", "every_days", "last_done_at",
                  "last_done_hours", "active"]

    def validate(self, data):
        hours = data.get("every_hours", getattr(self.instance, "every_hours", None))
        days = data.get("every_days", getattr(self.instance, "every_days", None))
        if not hours and not days:
            raise serializers.ValidationError("Set an interval in running hours, in days, or both.")
        return data


class MachineSerializer(serializers.ModelSerializer):
    work_center = serializers.SlugRelatedField(slug_field="code", queryset=WorkCenter.objects.all(),
                                               allow_null=True, required=False)
    hours = serializers.SerializerMethodField()
    downtime_30d = serializers.SerializerMethodField()
    open_logs = serializers.SerializerMethodField()
    plans = serializers.SerializerMethodField()
    state = serializers.SerializerMethodField()

    class Meta:
        model = Machine
        fields = ["id", "code", "name", "work_center", "make_model", "serial_no", "opening_hours", "hours_since",
                  "active", "notes", "hours", "downtime_30d", "state", "open_logs", "plans"]

    def _hours(self, obj):
        cache = self.context.setdefault("hours", {})
        if obj.id not in cache:
            cache[obj.id] = services.machine_hours(obj)
        return cache[obj.id]

    def get_hours(self, obj):
        return str(self._hours(obj))

    def get_downtime_30d(self, obj):
        return str(services.downtime_hours(obj))

    def get_open_logs(self, obj):
        return LogSerializer([l for l in obj.logs.all() if l.closed_at is None], many=True).data

    def get_plans(self, obj):
        h = self._hours(obj)
        return [services.plan_status(p, h) for p in obj.plans.all() if p.active]

    def get_state(self, obj):
        if any(l.closed_at is None and l.machine_down for l in obj.logs.all()):
            return "down"
        states = {p["state"] for p in self.get_plans(obj)}
        return "overdue" if "overdue" in states else "soon" if "soon" in states else "ok"


class BreakdownRequest(serializers.Serializer):
    description = serializers.CharField(max_length=240)
    machine_down = serializers.BooleanField(default=True)


class DoneRequest(serializers.Serializer):
    done_by = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    parts_cost = serializers.DecimalField(max_digits=12, decimal_places=2, default=Decimal(0), min_value=Decimal(0))


class CloseRequest(serializers.Serializer):
    action_taken = serializers.CharField()
    done_by = serializers.CharField(required=False, allow_blank=True, default="")
    parts_cost = serializers.DecimalField(max_digits=12, decimal_places=2, default=Decimal(0), min_value=Decimal(0))


class MachineViewSet(viewsets.ModelViewSet):
    queryset = Machine.objects.select_related("work_center").prefetch_related("logs__reported_by", "plans__machine")
    serializer_class = MachineSerializer
    lookup_field = "code"
    pagination_class = None
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    @action(detail=True, methods=["post"])
    def breakdown(self, request, code=None):
        req = BreakdownRequest(data=request.data)
        req.is_valid(raise_exception=True)
        log = services.report_breakdown(self.get_object(), user=request.user, **req.validated_data)
        return Response(LogSerializer(log).data, status=status.HTTP_201_CREATED)


class PlanViewSet(viewsets.ModelViewSet):
    queryset = MaintenancePlan.objects.select_related("machine")
    serializer_class = PlanSerializer
    pagination_class = None
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    @action(detail=True, methods=["post"])
    def done(self, request, pk=None):
        """Record that this service was carried out now; the next one is counted from here."""
        req = DoneRequest(data=request.data)
        req.is_valid(raise_exception=True)
        log = services.complete_plan(self.get_object(), user=request.user, **req.validated_data)
        return Response(LogSerializer(log).data, status=status.HTTP_201_CREATED)


class LogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MaintenanceLog.objects.select_related("machine", "reported_by")
    serializer_class = LogSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("machine"):
            qs = qs.filter(machine__code=p["machine"])
        if p.get("kind"):
            qs = qs.filter(kind=p["kind"])
        if p.get("open"):
            qs = qs.filter(closed_at__isnull=True)
        return qs

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        req = CloseRequest(data=request.data)
        req.is_valid(raise_exception=True)
        return Response(LogSerializer(services.close_log(self.get_object(), **req.validated_data)).data)


class DueView(APIView):
    def get(self, request):
        return Response(services.due_list())
