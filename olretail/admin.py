from django.contrib import admin
from .models import *
from modeltranslation.admin import TranslationAdmin


class CategoryAdmin(admin.ModelAdmin):
    list_display = ['title']
    prepopulated_fields ={'slug':('title',)}
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name']
    prepopulated_fields ={'slug':('name',)}

admin.site.register(Product, ProductAdmin)
admin.site.register(Category, CategoryAdmin)
admin.site.register(Country)
admin.site.register(City)
admin.site.register(Seller)
admin.site.register(Comment)



