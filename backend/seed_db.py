import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'breathe_esg_backend.settings')
django.setup()

from api.models import Organization, DataSource, PlantLookup

print("Seeding database...")

# Create Org
org, created = Organization.objects.get_or_create(id=1, defaults={'name': 'Breathe ESG Demo Org'})
if created:
    print(f"Created Org: {org.name}")
else:
    print(f"Org already exists: {org.name}")

# Create DataSources
sources = [
    (1, 'SAP', 'SAP ERP Fuel & Procurement Export'),
    (2, 'UTILITY', 'Utility PG&E Electricity portal'),
    (3, 'TRAVEL', 'Concur travel booking system')
]
for ds_id, s_type, name in sources:
    ds, created = DataSource.objects.get_or_create(
        id=ds_id,
        defaults={
            'organization': org,
            'source_type': s_type,
            'name': name
        }
    )
    if created:
        print(f"Created DataSource: {name}")
    else:
        print(f"DataSource exists: {name}")

# Create Plants
plants = [
    ('1001', 'Munich Plant', 'Munich, Germany', 'DE'),
    ('1002', 'Berlin Plant', 'Berlin, Germany', 'DE')
]
for p_code, p_name, loc, grid in plants:
    pl, created = PlantLookup.objects.get_or_create(
        organization=org,
        plant_code=p_code,
        defaults={
            'plant_name': p_name,
            'location': loc,
            'grid_region': grid
        }
    )
    if created:
        print(f"Created PlantLookup: {p_name}")
    else:
        print(f"PlantLookup exists: {p_name}")

print("Seeding completed successfully!")
