from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.catalog.api import ItemViewSet, ProductTemplateViewSet
from apps.core.api import LoginView, LogoutView, MeView
from apps.dispatch.api import DeliveryViewSet, InstallationViewSet, ReadyView
from apps.finance.api import AgingView, BillViewSet, InvoiceViewSet, SettingsView, TaxView, ToBillView, ToInvoiceView
from apps.inventory.api import (
    IssueView, LocationViewSet, LotViewSet, OffcutRegisterView, OffcutViewSet, ReceiveView, StockMoveViewSet,
    StockSummaryView,
)
from apps.maintenance.api import DueView, LogViewSet, MachineViewSet, PlanViewSet
from apps.production.api import NonConformanceViewSet, OperationViewSet, WorkCenterViewSet, WorkOrderViewSet
from apps.purchasing.api import (
    DraftOrdersView, PurchaseOrderViewSet, ShortagesView, SupplierItemViewSet, SupplierViewSet,
)
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
router.register("suppliers", SupplierViewSet)
router.register("supplier-items", SupplierItemViewSet)
router.register("purchase-orders", PurchaseOrderViewSet)
router.register("invoices", InvoiceViewSet)
router.register("supplier-bills", BillViewSet)
router.register("machines", MachineViewSet)
router.register("maintenance-plans", PlanViewSet)
router.register("maintenance-logs", LogViewSet)
router.register("deliveries", DeliveryViewSet)
router.register("installations", InstallationViewSet)

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
    path("api/purchasing/shortages/", ShortagesView.as_view()),
    path("api/purchasing/draft-orders/", DraftOrdersView.as_view()),
    path("api/maintenance/due/", DueView.as_view()),
    path("api/dispatch/ready/", ReadyView.as_view()),
    path("api/finance/to-invoice/", ToInvoiceView.as_view()),
    path("api/finance/to-bill/", ToBillView.as_view()),
    path("api/finance/aging/<str:side>/", AgingView.as_view()),
    path("api/finance/tax/", TaxView.as_view()),
    path("api/finance/settings/", SettingsView.as_view()),
    path("api/", include(router.urls)),
    path("api-auth/", include("rest_framework.urls")),
]
