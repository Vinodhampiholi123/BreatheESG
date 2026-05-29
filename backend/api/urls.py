from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DataSourceViewSet, NormalizedActivityViewSet, 
    IngestionJobListView, UploadCSVView, AuditLogListView, DashboardMetricsView
)

router = DefaultRouter()
router.register(r'data-sources', DataSourceViewSet, basename='data-sources')
router.register(r'activities', NormalizedActivityViewSet, basename='activities')

urlpatterns = [
    path('', include(router.urls)),
    path('upload-csv/', UploadCSVView.as_view(), name='upload-csv'),
    path('ingestion-jobs/', IngestionJobListView.as_view(), name='ingestion-jobs'),
    path('audit-logs/', AuditLogListView.as_view(), name='audit-logs'),
    path('dashboard-metrics/', DashboardMetricsView.as_view(), name='dashboard-metrics'),
]
