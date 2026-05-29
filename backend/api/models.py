from django.db import models

class Organization(models.Model):
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class DataSource(models.Model):
    SOURCE_TYPES = [
        ('SAP', 'SAP ERP Fuel & Procurement'),
        ('UTILITY', 'Utility Electricity Ingestion'),
        ('TRAVEL', 'Corporate Travel Ingestion'),
    ]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='data_sources')
    source_type = models.CharField(max_length=20, choices=SOURCE_TYPES)
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.source_type})"

class DataIngestionJob(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
    ]
    data_source = models.ForeignKey(DataSource, on_delete=models.CASCADE, related_name='ingestion_jobs')
    file_name = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Job {self.id} - {self.file_name} ({self.status})"

class RawDataRow(models.Model):
    ingestion_job = models.ForeignKey(DataIngestionJob, on_delete=models.CASCADE, related_name='raw_rows')
    raw_payload = models.JSONField()
    row_number = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Job {self.ingestion_job.id} - Row {self.row_number}"

class NormalizedActivity(models.Model):
    CATEGORY_CHOICES = [
        ('FUEL', 'Fuel & Procurement (SAP)'),
        ('ELECTRICITY', 'Electricity (Utility)'),
        ('TRAVEL', 'Corporate Travel (Flights/Ground)'),
    ]
    APPROVAL_CHOICES = [
        ('PENDING', 'Pending Review'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    ]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='normalized_activities')
    raw_row = models.OneToOneField(RawDataRow, on_delete=models.SET_NULL, null=True, blank=True, related_name='normalized_activity')
    data_source = models.ForeignKey(DataSource, on_delete=models.CASCADE, related_name='normalized_activities')
    ingestion_job = models.ForeignKey(DataIngestionJob, on_delete=models.CASCADE, related_name='normalized_activities')

    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    scope = models.IntegerField(choices=[(1, 'Scope 1'), (2, 'Scope 2'), (3, 'Scope 3')])
    activity_date = models.DateField()
    
    # Billing fields for utilities
    billing_period_start = models.DateField(null=True, blank=True)
    billing_period_end = models.DateField(null=True, blank=True)

    # Values & Units
    raw_value = models.DecimalField(max_digits=15, decimal_places=4)
    raw_unit = models.CharField(max_length=50)
    normalized_value = models.DecimalField(max_digits=15, decimal_places=4)
    normalized_unit = models.CharField(max_length=50)

    # Costs
    cost = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=10, default='USD')
    co2e_emissions = models.DecimalField(max_digits=15, decimal_places=6) # in Metric Tons of CO2e
    emission_factor_used = models.CharField(max_length=255)

    # Details
    description = models.TextField(blank=True, null=True)

    # Flags & Reviews
    is_suspicious = models.BooleanField(default=False)
    suspicion_reasons = models.JSONField(default=list, blank=True)

    approval_status = models.CharField(max_length=20, choices=APPROVAL_CHOICES, default='PENDING')
    approved_by = models.CharField(max_length=100, null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    is_locked = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.category} - {self.normalized_value} {self.normalized_unit} ({self.co2e_emissions} tCO2e)"

class AuditLog(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='audit_logs')
    activity = models.ForeignKey(NormalizedActivity, on_delete=models.CASCADE, related_name='audit_logs')
    user = models.CharField(max_length=100, default='Default Analyst')
    action = models.CharField(max_length=50) # e.g., EDIT, APPROVE, REJECT
    before_state = models.JSONField()
    after_state = models.JSONField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.action} on Activity {self.activity.id} by {self.user} at {self.timestamp}"

class PlantLookup(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    plant_code = models.CharField(max_length=50)
    plant_name = models.CharField(max_length=255)
    location = models.CharField(max_length=255)
    grid_region = models.CharField(max_length=100)

    class Meta:
        unique_together = ('organization', 'plant_code')

    def __str__(self):
        return f"{self.plant_code} - {self.plant_name} ({self.location})"
