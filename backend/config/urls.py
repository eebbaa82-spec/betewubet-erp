from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.catalog.api import ItemViewSet, ProductTemplateViewSet
from apps.inventory.api import LocationViewSet, LotViewSet, OffcutViewSet, StockMoveViewSet
from apps.production.api import OperationViewSet, WorkOrderViewSet
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

admin.site.site_header = "Betewubet ERP"
admin.site.site_title = "Betewubet ERP"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(router.urls)),
    path("api-auth/", include("rest_framework.urls")),
]
