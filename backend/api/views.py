import io
from decimal import Decimal
from django.utils import timezone
from django.db.models import Sum
from rest_framework import viewsets, status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser

from .models import (
    Organization, DataSource, DataIngestionJob, 
    NormalizedActivity, AuditLog, PlantLookup
)
from .serializers import (
    DataSourceSerializer, DataIngestionJobSerializer, 
    NormalizedActivitySerializer, AuditLogSerializer, PlantLookupSerializer
)
from .parsers import parse_sap_csv, parse_utility_csv, parse_travel_csv

class DataSourceViewSet(viewsets.ModelViewSet):
    queryset = DataSource.objects.all()
    serializer_class = DataSourceSerializer

class IngestionJobListView(generics.ListAPIView):
    queryset = DataIngestionJob.objects.all().order_by('-created_at')
    serializer_class = DataIngestionJobSerializer

class UploadCSVView(APIView):
    parser_classes = [MultiPartParser]

    def post(self, request, *args, **kwargs):
        data_source_id = request.data.get('data_source_id')
        file_obj = request.FILES.get('file')

        if not data_source_id or not file_obj:
            return Response(
                {"error": "Both 'data_source_id' and 'file' parameters are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            data_source = DataSource.objects.get(id=data_source_id)
        except DataSource.DoesNotExist:
            return Response(
                {"error": f"DataSource with ID {data_source_id} does not exist."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Create the Ingestion Job
        job = DataIngestionJob.objects.create(
            data_source=data_source,
            file_name=file_obj.name,
            status='PENDING'
        )

        try:
            # Decode file contents
            file_content = file_obj.read().decode('utf-8')
            csv_file_wrapper = io.StringIO(file_content)

            # Ingest based on source type
            if data_source.source_type == 'SAP':
                success, fail = parse_sap_csv(job, csv_file_wrapper)
            elif data_source.source_type == 'UTILITY':
                success, fail = parse_utility_csv(job, csv_file_wrapper)
            elif data_source.source_type == 'TRAVEL':
                success, fail = parse_travel_csv(job, csv_file_wrapper)
            else:
                raise ValueError(f"Unsupported source type: {data_source.source_type}")

            job.status = 'SUCCESS'
            job.save()

            return Response({
                "message": "CSV Ingested successfully.",
                "job": DataIngestionJobSerializer(job).data,
                "parsed_rows": success,
                "failed_rows": fail
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            job.status = 'FAILED'
            job.error_message = str(e)
            job.save()
            return Response({
                "error": f"CSV Import failed: {str(e)}",
                "job": DataIngestionJobSerializer(job).data
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class NormalizedActivityViewSet(viewsets.ModelViewSet):
    queryset = NormalizedActivity.objects.all().order_by('-created_at')
    serializer_class = NormalizedActivitySerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        category = self.request.query_params.get('category')
        approval_status = self.request.query_params.get('approval_status')
        is_suspicious = self.request.query_params.get('is_suspicious')
        scope = self.request.query_params.get('scope')

        if category:
            queryset = queryset.filter(category=category)
        if approval_status:
            queryset = queryset.filter(approval_status=approval_status)
        if is_suspicious:
            queryset = queryset.filter(is_suspicious=is_suspicious.lower() == 'true')
        if scope:
            queryset = queryset.filter(scope=int(scope))
            
        return queryset

    def update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        instance = self.get_object()
        
        if instance.is_locked:
            return Response(
                {"error": "This activity is approved and locked. Edits are no longer allowed for audit safety."},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        # Capture before state
        before_state = {
            "activity_date": str(instance.activity_date),
            "normalized_value": float(instance.normalized_value),
            "normalized_unit": instance.normalized_unit,
            "cost": float(instance.cost) if instance.cost else None,
            "currency": instance.currency,
            "co2e_emissions": float(instance.co2e_emissions),
            "description": instance.description
        }

        # Run standard update
        response = super().update(request, *args, **kwargs)
        
        # Refresh instance from DB to recalculate based on new inputs
        instance.refresh_from_db()
        
        # Recompute Emissions based on edited inputs
        val = instance.normalized_value
        category = instance.category
        ef = Decimal('2.0')
        ef_str = "Custom Edited Baseline Factor"
        
        if category == 'FUEL':
            desc_lower = (instance.description or '').lower()
            if 'diesel' in desc_lower:
                ef = Decimal('2.68')
                ef_str = "EPA Diesel factor (2.68 kg CO2e / Liter)"
            elif 'heizöl' in desc_lower or 'fuel oil' in desc_lower:
                ef = Decimal('2.96')
                ef_str = "EPA Fuel Oil factor (2.96 kg CO2e / Liter)"
            elif 'erdgas' in desc_lower or 'natural gas' in desc_lower:
                ef = Decimal('2.03')
                ef_str = "EPA Natural Gas factor (2.03 kg CO2e / kg)"
            instance.co2e_emissions = (val * ef) / Decimal('1000')
        elif category == 'ELECTRICITY':
            ef = Decimal('0.82')
            ef_str = "Standard Grid Electricity Factor (0.82 kg CO2e / kWh)"
            instance.co2e_emissions = (val * ef) / Decimal('1000')
        elif category == 'TRAVEL':
            desc_lower = (instance.description or '').lower()
            if 'business' in desc_lower or 'first' in desc_lower:
                ef = Decimal('0.29')
                ef_str = "DEFRA Flight Factor - Business/First Class (0.29 kg CO2e / km)"
            elif 'economy' in desc_lower:
                ef = Decimal('0.15')
                ef_str = "DEFRA Flight Factor - Economy Class (0.15 kg CO2e / km)"
            else:
                ef = Decimal('0.11')
                ef_str = "Standard Ground Transport Factor (0.11 kg CO2e / km)"
            instance.co2e_emissions = (val * ef) / Decimal('1000')

        instance.emission_factor_used = ef_str
        
        # Suspicion re-evaluations
        reasons = []
        is_suspicious = False
        if val <= 0:
            is_suspicious = True
            reasons.append("Value is zero or negative.")
        if category == 'ELECTRICITY' and val > 25000:
            is_suspicious = True
            reasons.append("Abnormally high energy consumption detected (> 25k kWh).")
            
        instance.is_suspicious = is_suspicious
        instance.suspicion_reasons = reasons
        instance.save()

        # Capture after state
        after_state = {
            "activity_date": str(instance.activity_date),
            "normalized_value": float(instance.normalized_value),
            "normalized_unit": instance.normalized_unit,
            "cost": float(instance.cost) if instance.cost else None,
            "currency": instance.currency,
            "co2e_emissions": float(instance.co2e_emissions),
            "description": instance.description
        }

        # Create Audit Log record
        AuditLog.objects.create(
            organization=instance.organization,
            activity=instance,
            user=request.data.get('editor_name', 'Default Analyst'),
            action='EDIT',
            before_state=before_state,
            after_state=after_state
        )

        return Response(NormalizedActivitySerializer(instance).data)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        instance = self.get_object()
        if instance.is_locked:
            return Response(
                {"error": "Activity already locked."},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        before_state = {"approval_status": instance.approval_status, "is_locked": instance.is_locked}
        
        instance.approval_status = 'APPROVED'
        instance.is_locked = True
        instance.approved_by = request.data.get('editor_name', 'Default Analyst')
        instance.approved_at = timezone.now()
        instance.save()
        
        after_state = {"approval_status": instance.approval_status, "is_locked": instance.is_locked}

        AuditLog.objects.create(
            organization=instance.organization,
            activity=instance,
            user=request.data.get('editor_name', 'Default Analyst'),
            action='APPROVE',
            before_state=before_state,
            after_state=after_state
        )

        return Response(NormalizedActivitySerializer(instance).data)

    @action(detail=False, methods=['post'])
    def bulk_approve(self, request):
        ids = request.data.get('ids', [])
        editor = request.data.get('editor_name', 'Default Analyst')
        
        if not ids:
            return Response({"error": "No IDs provided"}, status=status.HTTP_400_BAD_REQUEST)
            
        activities = NormalizedActivity.objects.filter(id__in=ids, is_locked=False)
        count = activities.count()
        
        for act in activities:
            before_state = {"approval_status": act.approval_status, "is_locked": act.is_locked}
            act.approval_status = 'APPROVED'
            act.is_locked = True
            act.approved_by = editor
            act.approved_at = timezone.now()
            act.save()
            
            after_state = {"approval_status": act.approval_status, "is_locked": act.is_locked}
            
            AuditLog.objects.create(
                organization=act.organization,
                activity=act,
                user=editor,
                action='APPROVE',
                before_state=before_state,
                after_state=after_state
            )
            
        return Response({"message": f"Successfully approved {count} activity records."}, status=status.HTTP_200_OK)

class AuditLogListView(generics.ListAPIView):
    serializer_class = AuditLogSerializer

    def get_queryset(self):
        activity_id = self.request.query_params.get('activity_id')
        if activity_id:
            return AuditLog.objects.filter(activity_id=activity_id).order_by('-timestamp')
        return AuditLog.objects.all().order_by('-timestamp')

class DashboardMetricsView(APIView):
    def get(self, request, *args, **kwargs):
        total_rows = NormalizedActivity.objects.count()
        total_emissions = NormalizedActivity.objects.aggregate(total=Sum('co2e_emissions'))['total'] or Decimal('0')
        pending_reviews = NormalizedActivity.objects.filter(approval_status='PENDING').count()
        suspicious_records = NormalizedActivity.objects.filter(is_suspicious=True).count()
        
        # Scope Splits
        scope1 = NormalizedActivity.objects.filter(scope=1).aggregate(total=Sum('co2e_emissions'))['total'] or Decimal('0')
        scope2 = NormalizedActivity.objects.filter(scope=2).aggregate(total=Sum('co2e_emissions'))['total'] or Decimal('0')
        scope3 = NormalizedActivity.objects.filter(scope=3).aggregate(total=Sum('co2e_emissions'))['total'] or Decimal('0')

        return Response({
            "total_rows": total_rows,
            "total_emissions_tco2e": round(float(total_emissions), 4),
            "pending_reviews": pending_reviews,
            "suspicious_records": suspicious_records,
            "scope_splits": {
                "scope1": round(float(scope1), 4),
                "scope2": round(float(scope2), 4),
                "scope3": round(float(scope3), 4)
            }
        })
