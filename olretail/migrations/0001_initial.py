# Generated by Django 3.1.4 on 2021-09-22 06:50

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Category',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('title_tt', models.CharField(max_length=200, null=True)),
                ('title_en', models.CharField(max_length=200, null=True)),
                ('slug', models.SlugField(unique=True)),
            ],
        ),
        migrations.CreateModel(
            name='City',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('city', models.CharField(max_length=100, unique=True)),
            ],
        ),
        migrations.CreateModel(
            name='Country',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('country', models.CharField(max_length=100, unique=True)),
            ],
        ),
        migrations.CreateModel(
            name='Seller',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('address', models.CharField(max_length=40)),
                ('mobile', models.CharField(max_length=20)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='Product',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('slug', models.SlugField()),
                ('product_image', models.ImageField(blank=True, null=True, upload_to='product_image')),
                ('product_image_2', models.ImageField(blank=True, default=True, upload_to='product_image')),
                ('product_image_3', models.ImageField(blank=True, default=True, upload_to='product_image')),
                ('price', models.DecimalField(decimal_places=2, max_digits=13)),
                ('description', models.TextField()),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
                ('quantity', models.PositiveIntegerField()),
                ('approved', models.BooleanField(default=False)),
                ('condition', models.CharField(choices=[('New', 'New'), ('Second Hand', 'Second Hand')], default=True, max_length=40)),
                ('category', models.ForeignKey(blank=True, on_delete=django.db.models.deletion.CASCADE, to='olretail.category')),
                ('country', models.ForeignKey(default=True, on_delete=django.db.models.deletion.CASCADE, to='olretail.country')),
                ('item_location', models.ForeignKey(blank=True, on_delete=django.db.models.deletion.CASCADE, to='olretail.city')),
                ('seller', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='olretail.seller')),
            ],
        ),
        migrations.CreateModel(
            name='Comment',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('commenter_name', models.CharField(max_length=200)),
                ('coment_body', models.TextField()),
                ('date_added', models.DateTimeField(auto_now=True)),
                ('product', models.ForeignKey(default=True, on_delete=django.db.models.deletion.CASCADE, to='olretail.product')),
            ],
        ),
        migrations.AddField(
            model_name='city',
            name='country',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='olretail.country'),
        ),
        migrations.CreateModel(
            name='Buyer',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('address', models.CharField(max_length=40)),
                ('mobile', models.CharField(max_length=40)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
