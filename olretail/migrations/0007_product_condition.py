# Generated by Django 3.1.4 on 2021-08-05 07:09

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('olretail', '0006_auto_20210805_1558'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='condition',
            field=models.CharField(choices=[('1', 'New'), ('2', 'Second')], default=True, max_length=40),
        ),
    ]
