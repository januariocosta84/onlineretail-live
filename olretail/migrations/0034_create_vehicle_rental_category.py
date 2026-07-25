from django.db import migrations


def create_vehicle_rental_category(apps, schema_editor):
    """A dedicated Category row for car/vehicle rental listings — distinct
    from the pre-existing "vehicles" category (for-sale vehicles). Its slug
    is in olretail.models.NON_CART_CATEGORY_SLUGS, which is what actually
    makes listings under it contact-the-seller-only instead of cart/checkout
    (see Product.cart_purchasable) — this migration only needs to create the
    row itself.

    Category.title is a django-modeltranslation field: the live model reads
    from title_en/title_tet shadow columns, but those aren't part of this
    migration's frozen historical model (modeltranslation injects them at
    app-load time, not via Django's migration state) — so title_en is set
    here with raw SQL alongside the plain fallback `title` column, mirroring
    migration 0021's create_restaurant_category."""
    Category = apps.get_model('olretail', 'Category')
    category, created = Category.objects.get_or_create(
        slug='vehicle-rental', defaults={'title': 'Vehicle Rental'}
    )
    if created:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(
                "UPDATE olretail_category SET title_en = %s WHERE id = %s",
                ['Vehicle Rental', category.pk],
            )


def remove_vehicle_rental_category(apps, schema_editor):
    Category = apps.get_model('olretail', 'Category')
    Category.objects.filter(slug='vehicle-rental').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('olretail', '0033_remove_courier_whatsapp'),
    ]

    operations = [
        migrations.RunPython(create_vehicle_rental_category, remove_vehicle_rental_category),
    ]
