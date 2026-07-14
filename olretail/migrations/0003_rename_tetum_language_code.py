"""Rename Category.title_tt -> title_tet.

The project used "tt" (Tatar in Django) as the language code for Tetum, which
pulled Django's bundled Tatar translations into the UI. The language code is
now "tet" (the correct ISO 639 code), so the modeltranslation column follows.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("olretail", "0002_data_integrity_and_field_fixes"),
    ]

    operations = [
        migrations.RenameField(
            model_name="category",
            old_name="title_tt",
            new_name="title_tet",
        ),
        migrations.AlterField(
            model_name="category",
            name="title_tet",
            field=models.CharField(max_length=200, null=True),
        ),
    ]
