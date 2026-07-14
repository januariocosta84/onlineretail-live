"""Product approval workflow.

Replaces the boolean `approved` with a five-state `status` field
(pending / approved / changes requested / rejected / suspended), adds the
moderation note shown to sellers, the homepage `featured` flag, and comment
visibility for moderation.
"""

from django.db import migrations, models


def approved_to_status(apps, schema_editor):
    Product = apps.get_model("olretail", "Product")
    Product.objects.filter(approved=True).update(status="approved")
    Product.objects.filter(approved=False).update(status="pending")


def status_to_approved(apps, schema_editor):
    Product = apps.get_model("olretail", "Product")
    Product.objects.filter(status="approved").update(approved=True)
    Product.objects.exclude(status="approved").update(approved=False)


class Migration(migrations.Migration):

    dependencies = [
        ("olretail", "0003_rename_tetum_language_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending approval"),
                    ("approved", "Published"),
                    ("changes", "Changes requested"),
                    ("rejected", "Rejected"),
                    ("suspended", "Suspended"),
                ],
                db_index=True,
                default="pending",
                max_length=12,
            ),
        ),
        migrations.RunPython(approved_to_status, status_to_approved),
        migrations.RemoveField(
            model_name="product",
            name="approved",
        ),
        migrations.AddField(
            model_name="product",
            name="moderation_note",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="product",
            name="featured",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="comment",
            name="is_public",
            field=models.BooleanField(default=True),
        ),
    ]
