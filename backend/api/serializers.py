from rest_framework import serializers
from .models import (
    Organization, DataSource, DataIngestionJob, 
    RawDataRow, NormalizedActivity, AuditLog, PlantLookup
)

class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = '__all__'

class DataSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataSource
        fields = '__all__'

class DataIngestionJobSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source='data_source.name', read_only=True)
    source_type = serializers.CharField(source='data_source.source_type', read_only=True)
    
    class Meta:
        model = DataIngestionJob
        fields = '__all__'

class RawDataRowSerializer(serializers.ModelSerializer):
    class Meta:
        model = RawDataRow
        fields = '__all__'

class NormalizedActivitySerializer(serializers.ModelSerializer):
    raw_payload = serializers.JSONField(source='raw_row.raw_payload', read_only=True)
    source_name = serializers.CharField(source='data_source.name', read_only=True)
    job_file = serializers.CharField(source='ingestion_job.file_name', read_only=True)

    class Meta:
        model = NormalizedActivity
        fields = '__all__'
        read_only_fields = [
            'organization', 'raw_row', 'data_source', 'ingestion_job',
            'category', 'scope', 'raw_value', 'raw_unit', 'normalized_unit',
            'co2e_emissions', 'emission_factor_used', 'is_suspicious',
            'suspicion_reasons', 'approval_status', 'approved_by', 'approved_at',
            'is_locked'
        ]

class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = '__all__'

class PlantLookupSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlantLookup
        fields = '__all__'
