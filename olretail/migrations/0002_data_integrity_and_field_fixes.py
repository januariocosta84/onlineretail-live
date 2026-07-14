"""Data-integrity fixes for the original 2021 schema.

* De-duplicates product slugs (the old model allowed duplicates, which made
  the product detail page crash), then enforces uniqueness.
* Removes nonsensical field defaults (default=True on ImageField / FK /
  CharField) that broke product creation when optional fields were omitted.
* Renames Comment.coment_body -> body and links comments to products with a
  related_name so the detail page can show per-product comments.
"""

from django.db import migrations, models
import django.db.models.deletion
from django.utils.text import slugify


def dedupe_product_slugs(apps, schema_editor):
    Product = apps.get_model("olretail", "Product")
    seen = set()
    for product in Product.objects.order_by("pk"):
        base = slugify(product.name)[:200] or "product"
        slug = base
        counter = 2
        while slug in seen:
            slug = f"{base}-{counter}"
            counter += 1
        seen.add(slug)
        if product.slug != slug:
            product.slug = slug
            product.save(update_fields=["slug"])


class Migration(migrations.Migration):

    dependencies = [
        ("olretail", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(dedupe_product_slugs, migrations.RunPython.noop),
        migrations.AlterModelOptions(
            name="category",
            options={"ordering": ["title"], "verbose_name_plural": "Categories"},
        ),
        migrations.AlterModelOptions(
            name="city",
            options={"ordering": ["city"], "verbose_name_plural": "Cities"},
        ),
        migrations.AlterModelOptions(
            name="comment",
            options={"ordering": ["-date_added"]},
        ),
        migrations.AlterModelOptions(
            name="country",
            options={"ordering": ["country"], "verbose_name_plural": "Countries"},
        ),
        migrations.AlterModelOptions(
            name="product",
            options={"ordering": ["-created"]},
        ),
        migrations.AlterField(
            model_name="buyer",
            name="address",
            field=models.CharField(max_length=255),
        ),
        migrations.AlterField(
            model_name="seller",
            name="address",
            field=models.CharField(max_length=255),
        ),
        migrations.AlterField(
            model_name="seller",
            name="mobile",
            field=models.CharField(max_length=40),
        ),
        migrations.AlterField(
            model_name="product",
            name="slug",
            field=models.SlugField(max_length=220, unique=True),
        ),
        migrations.AlterField(
            model_name="product",
            name="product_image_2",
            field=models.ImageField(blank=True, upload_to="product_image"),
        ),
        migrations.AlterField(
            model_name="product",
            name="product_image_3",
            field=models.ImageField(blank=True, upload_to="product_image"),
        ),
        migrations.AlterField(
            model_name="product",
            name="category",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, to="olretail.category"
            ),
        ),
        migrations.AlterField(
            model_name="product",
            name="country",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, to="olretail.country"
            ),
        ),
        migrations.AlterField(
            model_name="product",
            name="item_location",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, to="olretail.city"
            ),
        ),
        migrations.AlterField(
            model_name="product",
            name="condition",
            field=models.CharField(
                choices=[("New", "New"), ("Second Hand", "Second Hand")],
                default="New",
                max_length=40,
            ),
        ),
        migrations.AlterField(
            model_name="product",
            name="approved",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.RenameField(
            model_name="comment",
            old_name="coment_body",
            new_name="body",
        ),
        migrations.AlterField(
            model_name="comment",
            name="date_added",
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterField(
            model_name="comment",
            name="product",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="comments",
                to="olretail.product",
            ),
        ),
    ]
