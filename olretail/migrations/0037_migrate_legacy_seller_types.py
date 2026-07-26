from django.db import migrations


def migrate_legacy_seller_types(apps, schema_editor):
    """SellerType dropped 'company'/'restaurant' in favor of
    'registered_business' (Restaurant moved to being a BusinessCategory
    instead of a SellerType — see SellerType's docstring). Existing sellers:
    - 'company' -> 'registered_business' (straight relabel).
    - 'restaurant' -> 'registered_business', tagged with the Restaurant
      BusinessCategory so nothing that depended on "is this a restaurant"
      (menu sections, the admin restaurants queue) loses that information.
    - 'individual' is untouched.
    """
    Seller = apps.get_model('olretail', 'Seller')
    restaurant_category = apps.get_model('olretail', 'BusinessCategory').objects.filter(
        slug='restaurant'
    ).first()

    Seller.objects.filter(seller_type='company').update(seller_type='registered_business')

    restaurant_sellers = Seller.objects.filter(seller_type='restaurant')
    restaurant_seller_ids = list(restaurant_sellers.values_list('id', flat=True))
    restaurant_sellers.update(seller_type='registered_business')

    if restaurant_category is not None and restaurant_seller_ids:
        M2MThrough = Seller.business_categories.through
        already_linked = set(
            M2MThrough.objects.filter(
                seller_id__in=restaurant_seller_ids, businesscategory_id=restaurant_category.id
            ).values_list('seller_id', flat=True)
        )
        M2MThrough.objects.bulk_create([
            M2MThrough(seller_id=seller_id, businesscategory_id=restaurant_category.id)
            for seller_id in restaurant_seller_ids
            if seller_id not in already_linked
        ])


def reverse_noop(apps, schema_editor):
    """Not reversible: both legacy 'company' and 'restaurant' merge into the
    same 'registered_business' value, so there's no way to tell which
    sellers to relabel back to which original value. Intentionally a no-op,
    same as this codebase's other one-way data migrations."""


class Migration(migrations.Migration):

    dependencies = [
        ('olretail', '0036_seed_municipalities_and_business_categories'),
    ]

    operations = [
        migrations.RunPython(migrate_legacy_seller_types, reverse_noop),
    ]
