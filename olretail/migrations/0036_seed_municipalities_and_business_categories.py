from django.db import migrations
from django.utils.text import slugify

# 13 municipalities + the Oecusse special administrative region, per
# Timor-Leste's current administrative division (including Atauro as its
# own municipality since the 2022 reform, previously an administrative
# post of Dili). Confirm against an authoritative current source (e.g. the
# government gazette or INE) before relying on this list being exhaustive —
# it was not sourced from an official dataset in this session.
MUNICIPALITIES = [
    "Aileu", "Ainaro", "Atauro", "Baucau", "Bobonaro", "Covalima", "Dili",
    "Ermera", "Manatuto", "Manufahi", "Lautém", "Liquiçá", "Viqueque", "Oecusse",
]

BUSINESS_CATEGORIES = [
    "Electronics", "Mobile Phones", "Computers", "Fashion", "Shoes",
    "Beauty & Cosmetics", "Food & Beverage", "Restaurant", "Coffee Shop",
    "Grocery", "Agriculture", "Fishery", "Furniture", "Home & Living",
    "Automotive", "Construction & Hardware", "Books & Stationery", "Services",
    "Digital Products", "Handicrafts", "Local Products",
]


def seed_municipalities_and_business_categories(apps, schema_editor):
    Municipality = apps.get_model('olretail', 'Municipality')
    BusinessCategory = apps.get_model('olretail', 'BusinessCategory')
    for name in MUNICIPALITIES:
        Municipality.objects.get_or_create(name=name)
    for title in BUSINESS_CATEGORIES:
        BusinessCategory.objects.get_or_create(slug=slugify(title), defaults={'title': title})


def remove_municipalities_and_business_categories(apps, schema_editor):
    Municipality = apps.get_model('olretail', 'Municipality')
    BusinessCategory = apps.get_model('olretail', 'BusinessCategory')
    Municipality.objects.filter(name__in=MUNICIPALITIES).delete()
    BusinessCategory.objects.filter(slug__in=[slugify(t) for t in BUSINESS_CATEGORIES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('olretail', '0035_businesscategory_municipality_and_more'),
    ]

    operations = [
        migrations.RunPython(
            seed_municipalities_and_business_categories,
            remove_municipalities_and_business_categories,
        ),
    ]
