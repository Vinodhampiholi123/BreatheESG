import csv
import io
import json
from datetime import datetime
from decimal import Decimal
from django.utils import timezone
from .models import (
    DataSource, DataIngestionJob, RawDataRow, 
    NormalizedActivity, PlantLookup, Organization
)

# Helper: parse date safely
def parse_date(date_str):
    for fmt in ('%Y-%m-%d', '%Y.%m.%d', '%d.%m.%Y', '%d-%m-%Y', '%Y/%m/%d', '%d/%m/%Y'):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unable to parse date: {date_str}")

# Helper: safe decimal
def safe_decimal(val_str, default=Decimal('0')):
    if not val_str:
        return default
    try:
        # replace comma with dot for European numbering format (e.g. 1.250,50 -> 1250.50)
        clean_str = val_str.strip().replace('.', '').replace(',', '.')
        if clean_str.count('.') > 1:
            # If multiple dots, might have been a simple separator like 120.000.50, resolve
            parts = clean_str.split('.')
            clean_str = "".join(parts[:-1]) + "." + parts[-1]
        return Decimal(clean_str)
    except Exception:
        # Fallback to simple float cleaning
        try:
            return Decimal(str(float(val_str.strip())))
        except Exception:
            return default

def parse_sap_csv(job, csv_file_wrapper):
    """
    Parses SAP fuel and procurement CSV data.
    Expected Columns:
    Materialbeleg, Buchungsdatum, Material, Menge, Einheit, Werk, Betrag, Waers
    """
    reader = csv.DictReader(csv_file_wrapper)
    success_count = 0
    fail_count = 0
    
    # Pre-fetch lookup plants
    org = job.data_source.organization
    valid_plants = set(PlantLookup.objects.filter(organization=org).values_list('plant_code', flat=True))

    for idx, row in enumerate(reader):
        row_num = idx + 2 # Header is row 1
        
        # Save raw row first for full data lineage
        raw_row = RawDataRow.objects.create(
            ingestion_job=job,
            raw_payload=row,
            row_number=row_num
        )
        
        try:
            material_doc = row.get('Materialbeleg', '').strip()
            date_str = row.get('Buchungsdatum', '').strip()
            material = row.get('Material', '').strip()
            qty_str = row.get('Menge', '').strip()
            unit = row.get('Einheit', '').strip()
            plant_code = row.get('Werk', '').strip()
            cost_str = row.get('Betrag', '').strip()
            currency = row.get('Waers', 'EUR').strip()
            
            if not date_str or not material or not qty_str:
                raise ValueError("Missing critical fields: Date, Material, or Quantity")
                
            activity_date = parse_date(date_str)
            raw_val = safe_decimal(qty_str)
            raw_cost = safe_decimal(cost_str)
            
            # Normalization logic
            suspicious = False
            reasons = []
            
            # Convert units
            normalized_val = raw_val
            normalized_unit = unit
            
            # Unit lookup mapping
            unit_upper = unit.upper()
            if unit_upper in ('L', 'LITER', 'LITERS'):
                normalized_unit = 'Liters'
            elif unit_upper in ('GLL', 'GAL', 'GALLON', 'GALLONS'):
                normalized_unit = 'Liters'
                normalized_val = raw_val * Decimal('3.78541')
            elif unit_upper in ('KG', 'KILOGRAM', 'KILOGRAMS'):
                normalized_unit = 'kg'
            else:
                suspicious = True
                reasons.append(f"Unrecognized unit '{unit}'. Kept original value.")
                
            if raw_val <= 0:
                suspicious = True
                reasons.append("Fuel quantity is zero or negative.")

            # Plant verification
            plant_desc = f"Plant {plant_code}"
            if plant_code not in valid_plants:
                suspicious = True
                reasons.append(f"Unrecognized Plant Code '{plant_code}'. Source mapping lookup failed.")
            else:
                plant_obj = PlantLookup.objects.get(organization=org, plant_code=plant_code)
                plant_desc = f"{plant_obj.plant_name} ({plant_obj.location})"

            # Emission Factor logic
            mat_lower = material.lower()
            ef = Decimal('2.0') # default suspicious fallback
            ef_str = "Standard Fallback Factor (2.0 kg CO2e/unit)"
            
            if 'diesel' in mat_lower:
                ef = Decimal('2.68')
                ef_str = "EPA Diesel factor (2.68 kg CO2e / Liter)"
            elif 'heizöl' in mat_lower or 'fuel oil' in mat_lower or 'heating oil' in mat_lower:
                ef = Decimal('2.96')
                ef_str = "EPA Fuel Oil factor (2.96 kg CO2e / Liter)"
            elif 'erdgas' in mat_lower or 'natural gas' in mat_lower:
                ef = Decimal('2.03')
                ef_str = "EPA Natural Gas factor (2.03 kg CO2e / kg)"
            else:
                suspicious = True
                reasons.append(f"Unrecognized material description '{material}'. Calculated with standard baseline.")

            # Calculate emissions: value * factor / 1000 to convert kg CO2e into Metric Tons (tCO2e)
            emissions = (normalized_val * ef) / Decimal('1000')
            
            description = f"SAP Import: Document {material_doc}, Material: {material}, Plant: {plant_desc}"
            
            # Create Normalized record
            NormalizedActivity.objects.create(
                organization=org,
                raw_row=raw_row,
                data_source=job.data_source,
                ingestion_job=job,
                category='FUEL',
                scope=1,
                activity_date=activity_date,
                raw_value=raw_val,
                raw_unit=unit,
                normalized_value=normalized_val,
                normalized_unit=normalized_unit,
                cost=raw_cost,
                currency=currency,
                co2e_emissions=emissions,
                emission_factor_used=ef_str,
                description=description,
                is_suspicious=suspicious,
                suspicion_reasons=reasons
            )
            success_count += 1
            
        except Exception as e:
            fail_count += 1
            # Mark raw row as failed inside some lookup or simply print
            print(f"Error parsing row {row_num}: {e}")

    return success_count, fail_count

def parse_utility_csv(job, csv_file_wrapper):
    """
    Parses Utility electricity portal CSV data.
    Expected Columns:
    Account Number, Meter Number, Billing Start Date, Billing End Date, Usage (kWh), Rate Code, Total Charges, Currency
    """
    reader = csv.DictReader(csv_file_wrapper)
    success_count = 0
    fail_count = 0
    org = job.data_source.organization

    for idx, row in enumerate(reader):
        row_num = idx + 2
        
        raw_row = RawDataRow.objects.create(
            ingestion_job=job,
            raw_payload=row,
            row_number=row_num
        )
        
        try:
            account_num = row.get('Account Number', '').strip()
            meter_num = row.get('Meter Number', '').strip()
            start_str = row.get('Billing Start Date', '').strip()
            end_str = row.get('Billing End Date', '').strip()
            usage_str = row.get('Usage (kWh)', '').strip()
            rate_code = row.get('Rate Code', 'COMMERCIAL').strip()
            cost_str = row.get('Total Charges', '').strip()
            currency = row.get('Currency', 'USD').strip()
            
            if not end_str or not usage_str:
                raise ValueError("Missing critical fields: Billing End Date or Usage (kWh)")
                
            activity_date = parse_date(end_str)
            start_date = parse_date(start_str) if start_str else None
            
            raw_val = safe_decimal(usage_str)
            raw_cost = safe_decimal(cost_str)
            
            suspicious = False
            reasons = []
            
            if raw_val <= 0:
                suspicious = True
                reasons.append("Electricity usage is zero or negative.")
            if raw_cost <= 0:
                suspicious = True
                reasons.append("Billing charge is zero or negative.")
            if raw_val > Decimal('25000'):
                suspicious = True
                reasons.append(f"Abnormally high energy consumption detected (> 25k kWh: {raw_val} kWh).")
                
            # Static Emission Factor for Grid Electricity: 0.82 kg CO2e / kWh
            ef = Decimal('0.82')
            ef_str = "Standard Grid Electricity Factor (0.82 kg CO2e / kWh)"
            
            # Emissions: (kWh * 0.82) / 1000 = metric tons CO2e
            emissions = (raw_val * ef) / Decimal('1000')
            
            description = f"Electricity Bill: Acct {account_num}, Meter {meter_num}, Rate {rate_code}"
            
            NormalizedActivity.objects.create(
                organization=org,
                raw_row=raw_row,
                data_source=job.data_source,
                ingestion_job=job,
                category='ELECTRICITY',
                scope=2,
                activity_date=activity_date,
                billing_period_start=start_date,
                billing_period_end=activity_date,
                raw_value=raw_val,
                raw_unit='kWh',
                normalized_value=raw_val,
                normalized_unit='kWh',
                cost=raw_cost,
                currency=currency,
                co2e_emissions=emissions,
                emission_factor_used=ef_str,
                description=description,
                is_suspicious=suspicious,
                suspicion_reasons=reasons
            )
            success_count += 1
            
        except Exception as e:
            fail_count += 1
            print(f"Error parsing row {row_num}: {e}")

    return success_count, fail_count

def parse_travel_csv(job, csv_file_wrapper):
    """
    Parses Corporate travel platform CSV data.
    Expected Columns:
    Employee ID, Travel Category, Origin, Destination, Distance (km), Class, Cost, Currency
    """
    reader = csv.DictReader(csv_file_wrapper)
    success_count = 0
    fail_count = 0
    org = job.data_source.organization
    
    # Predefined simple IATA Great-Circle band distances (fallback list)
    iata_distances = {
        ('SFO', 'JFK'): Decimal('4150'),
        ('JFK', 'SFO'): Decimal('4150'),
        ('LHR', 'JFK'): Decimal('5540'),
        ('JFK', 'LHR'): Decimal('5540'),
        ('CDG', 'LHR'): Decimal('350'),
        ('LHR', 'CDG'): Decimal('350'),
        ('CDG', 'JFK'): Decimal('5830'),
        ('JFK', 'CDG'): Decimal('5830'),
    }

    for idx, row in enumerate(reader):
        row_num = idx + 2
        
        raw_row = RawDataRow.objects.create(
            ingestion_job=job,
            raw_payload=row,
            row_number=row_num
        )
        
        try:
            employee_id = row.get('Employee ID', '').strip()
            category = row.get('Travel Category', 'Flight').strip()
            origin = row.get('Origin', '').strip().upper()
            destination = row.get('Destination', '').strip().upper()
            distance_str = row.get('Distance (km)', '').strip()
            travel_class = row.get('Class', 'Economy').strip()
            cost_str = row.get('Cost', '').strip()
            currency = row.get('Currency', 'USD').strip()
            
            raw_val = safe_decimal(distance_str)
            raw_cost = safe_decimal(cost_str)
            
            suspicious = False
            reasons = []
            
            # Distance resolution
            normalized_val = raw_val
            
            # Flight distance calculations based on IATA lookups
            is_flight = 'flight' in category.lower() or 'air' in category.lower()
            
            if is_flight and (not normalized_val or normalized_val == 0):
                # Lookup IATA pair
                iata_pair = (origin, destination)
                if iata_pair in iata_distances:
                    normalized_val = iata_distances[iata_pair]
                else:
                    normalized_val = Decimal('1000') # standard fallback distance
                    suspicious = True
                    reasons.append(f"Airport pair '{origin}-{destination}' not found in standard lookup list. Assigned default fallback (1000 km).")
            
            if normalized_val <= 0:
                suspicious = True
                reasons.append("Travel distance is zero or negative.")
                
            # Travel Emission Factors
            if is_flight:
                class_lower = travel_class.lower()
                if 'business' in class_lower or 'first' in class_lower:
                    ef = Decimal('0.29')
                    ef_str = "DEFRA Flight Factor - Business/First Class (0.29 kg CO2e / passenger-km)"
                else:
                    ef = Decimal('0.15')
                    ef_str = "DEFRA Flight Factor - Economy Class (0.15 kg CO2e / passenger-km)"
            else:
                ef = Decimal('0.11')
                ef_str = "Standard Ground Transport Factor (0.11 kg CO2e / passenger-km)"
                
            # Emissions: (passenger-km * factor) / 1000 = metric tons CO2e
            emissions = (normalized_val * ef) / Decimal('1000')
            
            desc_details = f"Flight: {origin} -> {destination} ({travel_class} class)" if is_flight else f"Ground: {category}"
            description = f"Corporate Travel - Emp {employee_id}. {desc_details}"
            
            NormalizedActivity.objects.create(
                organization=org,
                raw_row=raw_row,
                data_source=job.data_source,
                ingestion_job=job,
                category='TRAVEL',
                scope=3,
                activity_date=datetime.now().date(), # Default to current date for travel expense imports
                raw_value=raw_val,
                raw_unit='km',
                normalized_value=normalized_val,
                normalized_unit='passenger-km',
                cost=raw_cost,
                currency=currency,
                co2e_emissions=emissions,
                emission_factor_used=ef_str,
                description=description,
                is_suspicious=suspicious,
                suspicion_reasons=reasons
            )
            success_count += 1
            
        except Exception as e:
            fail_count += 1
            print(f"Error parsing row {row_num}: {e}")

    return success_count, fail_count
