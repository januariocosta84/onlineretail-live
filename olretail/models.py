from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import UserManager
from django.contrib.auth.models import AbstractUser

from django.utils.text import slugify

condition =(
    ("New", "New"),
    ("Second Hand", "Second Hand")

)

class Buyer(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    address = models.CharField(max_length=40)
    mobile = models.CharField(max_length=40)


    @property
    def get_name(self):
        return self.user.first_name+" "+self.user.last_name

    @property
    def get_id(self):
        return self.user.id

    def __str__(self):
        return self.user.first_name


class Seller(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    address = models.CharField(max_length=40)
    mobile = models.CharField(max_length=20, null=False)
   

    @property
    def get_name(self):
        return self.user.first_name+" "+self.user.last_name

    @property
    def get_id(self):
        return self.user.id

    def __str__(self):
        return self.user.first_name

"""
Class Address
"""
class Country(models.Model):
    country = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.country

'''City Class'''
class City(models.Model):
    city = models.CharField(max_length=100, unique=True)
    country = models.ForeignKey(Country, on_delete=models.CASCADE)

    def __str__(self):
        return self.city


'''Category class'''
class Category(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)

    def __str__(self):
        return self.title

'''Product Class'''
class Product(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField()
    product_image = models.ImageField(
        upload_to='product_image', null=True, blank=True)
    product_image_2 = models.ImageField(upload_to='product_image', blank=True, default=True)
    product_image_3 = models.ImageField(upload_to='product_image', blank=True, default=True)
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, blank=True)
    price = models.DecimalField(max_digits=13, decimal_places=2)
    description = models.TextField()
    country = models.ForeignKey(Country, on_delete=models.CASCADE, default=True)
    item_location = models.ForeignKey(
        City, on_delete=models.CASCADE, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    quantity = models.PositiveIntegerField()
    seller = models.ForeignKey(Seller, on_delete=models.CASCADE)
    approved = models.BooleanField(default=False)
    condition = models.CharField(max_length=40, choices=condition, default=True)

    #status = models.CharField()
    def save(self, *args, **kwargs):
        self.slug = slugify(self.name)
        super(Product, self).save(*args, **kwargs)
    def __str__(self):
        return self.name

'''Comment Area'''
class Comment(models.Model):
    product = models.ForeignKey(Product, on_delete= models.CASCADE, default=True)
    commenter_name = models.CharField(max_length=200)
    coment_body  = models.TextField()
    date_added = models.DateTimeField(auto_now=True)

    def __str__(self):
       return '%s - %s' %(self.product, self.commenter_name)
