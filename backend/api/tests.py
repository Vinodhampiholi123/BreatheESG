import io
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from .models import (
    Organization, DataSource, DataIngestionJob, 
    NormalizedActivity, AuditLog, PlantLookup
)
from .parsers import parse_sap_csv, parse_utility_csv, parse_travel_csv

class ESGPlatformTestCase(TestCase):
    def setUp(self):
        # Seed Org
        self.org = Organization.objects.create(name="Test Org")
        
        # Seed Sources
        self.sap_source = DataSource.objects.create(
            organization=self.org,
            source_type='SAP',
            name="SAP Source"
        )
        self.utility_source = DataSource.objects.create(
            organization=self.org,
            source_type='UTILITY',
            name="Utility Source"
        )
        self.travel_source = DataSource.objects.create(
            organization=self.org,
            source_type='TRAVEL',
            name="Travel Source"
        )
        
        # Seed Plant Lookups
        self.plant_1001 = PlantLookup.objects.create(
            organization=self.org,
            plant_code="1001",
            plant_name="Munich HQ",
            location="Munich, Germany",
            grid_region="DE"
        )

    def test_sap_ingestion_success(self):
        job = DataIngestionJob.objects.create(
            data_source=self.sap_source,
            file_name="test_sap.csv"
        )
        
        csv_data = (
            "Materialbeleg,Buchungsdatum,Material,Menge,Einheit,Werk,Betrag,Waers\n"
            "MB-001,2026.04.15,Diesel Fuel,1000,L,1001,1200,EUR\n"
            "MB-002,2026.04.18,Heizöl,100,GLL,1001,450,EUR\n"
        )
        
        csv_file = io.StringIO(csv_data)
        success, fail = parse_sap_csv(job, csv_file)
        
        self.assertEqual(success, 2)
        self.assertEqual(fail, 0)
        
        activities = NormalizedActivity.objects.filter(ingestion_job=job)
        self.assertEqual(activities.count(), 2)
        
        # Verify Diesel: 1000 L -> 1000 L * 2.68 kg/L / 1000 = 2.68 tCO2e
        diesel = activities.get(description__contains="Diesel")
        self.assertEqual(diesel.normalized_value, Decimal('1000'))
        self.assertEqual(diesel.normalized_unit, 'Liters')
        self.assertEqual(diesel.co2e_emissions, Decimal('2.680000'))
        self.assertFalse(diesel.is_suspicious)
        
        # Verify Heizöl: 100 Gallons -> 378.541 Liters * 2.96 kg/L / 1000 = 1.120481 tCO2e
        oil = activities.get(description__contains="Heizöl")
        self.assertAlmostEqual(float(oil.normalized_value), 378.541, places=3)
        self.assertEqual(oil.normalized_unit, 'Liters')
        self.assertAlmostEqual(float(oil.co2e_emissions), 1.12048, places=4)

    def test_utility_ingestion_suspicious_spike(self):
        job = DataIngestionJob.objects.create(
            data_source=self.utility_source,
            file_name="test_utility.csv"
        )
        
        csv_data = (
            "Account Number,Meter Number,Billing Start Date,Billing End Date,Usage (kWh),Rate Code,Total Charges,Currency\n"
            "ACC-01,MET-01,2026-04-01,2026-04-30,30000,COMM,4500,USD\n"
        )
        
        csv_file = io.StringIO(csv_data)
        success, fail = parse_utility_csv(job, csv_file)
        
        self.assertEqual(success, 1)
        
        act = NormalizedActivity.objects.get(ingestion_job=job)
        self.assertTrue(act.is_suspicious)
        self.assertIn("Abnormally high energy consumption", act.suspicion_reasons[0])
        # Emissions: 30000 * 0.82 / 1000 = 24.6 tCO2e
        self.assertEqual(act.co2e_emissions, Decimal('24.600000'))

    def test_travel_distance_iata_lookup(self):
        job = DataIngestionJob.objects.create(
            data_source=self.travel_source,
            file_name="test_travel.csv"
        )
        
        csv_data = (
            "Employee ID,Travel Category,Origin,Destination,Distance (km),Class,Cost,Currency\n"
            "EMP-01,Flight,LHR,JFK,0,Business,1500,USD\n"
        )
        
        csv_file = io.StringIO(csv_data)
        success, fail = parse_travel_csv(job, csv_file)
        
        self.assertEqual(success, 1)
        
        act = NormalizedActivity.objects.get(ingestion_job=job)
        # Distance should resolve from LHR-JFK hardcode to 5540 km
        self.assertEqual(act.normalized_value, Decimal('5540'))
        # Emissions: 5540 km * 0.29 (Business factor) / 1000 = 1.6066 tCO2e
        self.assertAlmostEqual(float(act.co2e_emissions), 1.6066, places=4)
        self.assertFalse(act.is_suspicious)

    def test_manual_override_audit_logs(self):
        # Create a basic record
        job = DataIngestionJob.objects.create(
            data_source=self.sap_source,
            file_name="test_audit.csv"
        )
        
        act = NormalizedActivity.objects.create(
            organization=self.org,
            data_source=self.sap_source,
            ingestion_job=job,
            category='FUEL',
            scope=1,
            activity_date=timezone.now().date(),
            raw_value=Decimal('500'),
            raw_unit='L',
            normalized_value=Decimal('500'),
            normalized_unit='Liters',
            co2e_emissions=Decimal('1.340000'), # 500 * 2.68 / 1000
            emission_factor_used="EPA Diesel factor (2.68 kg CO2e / Liter)",
            description="Diesel fuel row"
        )
        
        # Simulate view override update
        before_state = {
            "normalized_value": float(act.normalized_value),
            "co2e_emissions": float(act.co2e_emissions)
        }
        
        # Override update
        act.normalized_value = Decimal('1000')
        act.co2e_emissions = (act.normalized_value * Decimal('2.68')) / Decimal('1000')
        act.save()
        
        after_state = {
            "normalized_value": float(act.normalized_value),
            "co2e_emissions": float(act.co2e_emissions)
        }
        
        AuditLog.objects.create(
            organization=self.org,
            activity=act,
            user="Venkatesh S H",
            action="EDIT",
            before_state=before_state,
            after_state=after_state
        )
        
        logs = AuditLog.objects.filter(activity=act)
        self.assertEqual(logs.count(), 1)
        log = logs.first()
        self.assertEqual(log.user, "Venkatesh S H")
        self.assertEqual(log.action, "EDIT")
        self.assertEqual(log.before_state["normalized_value"], 500.0)
        self.assertEqual(log.after_state["normalized_value"], 1000.0)
        self.assertEqual(log.after_state["co2e_emissions"], 2.68)
