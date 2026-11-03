from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.catalog.api import ItemViewSet, ProductTemplateViewSet
from apps.core.api import LoginView, LogoutView, MeView
from apps.inventory.api import (
    IssueView, LocationViewSet, LotViewSet, OffcutRegisterView, OffcutViewSet, ReceiveView, StockMoveViewSet,
    StockSummaryView,
)
from apps.production.api import NonConformanceViewSet, OperationViewSet, WorkCenterViewSet, WorkOrderViewSet
from apps.sales.api import CustomerViewSet, SalesOrderLineViewSet, SalesOrderViewSet

router = DefaultRouter()
router.register("items", ItemViewSet)
router.register("templates", ProductTemplateViewSet)
router.register("locations", LocationViewSet)
router.register("lots", LotViewSet)
router.register("stock-moves", StockMoveViewSet)
router.register("offcuts", OffcutViewSet)
router.register("customers", CustomerViewSet)
router.register("sales-orders", SalesOrderViewSet)
router.register("sales-order-lines", SalesOrderLineViewSet)
router.register("work-orders", WorkOrderViewSet)
router.register("operations", OperationViewSet, basename="operation")
router.register("work-centers", WorkCenterViewSet)
router.register("non-conformances", NonConformanceViewSet)

admin.site.site_header = "Betewubet ERP"
admin.site.site_title = "Betewubet ERP"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/me/", MeView.as_view()),
    path("api/auth/login/", LoginView.as_view()),
    path("api/auth/logout/", LogoutView.as_view()),
    path("api/stock/", StockSummaryView.as_view()),
    path("api/stock/receive/", ReceiveView.as_view()),
    path("api/stock/issue/", IssueView.as_view()),
    path("api/offcuts/register/", OffcutRegisterView.as_view()),
    path("api/", include(router.urls)),
    path("api-auth/", include("rest_framework.urls")),
]
