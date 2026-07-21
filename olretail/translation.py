from django.conf import settings
from django.utils.translation import gettext_lazy
from modeltranslation.translator import translator, register, TranslationOptions

from .models import Category, Product

class TranslateCat(TranslationOptions):
    fields=('title',)
translator.register(Category, TranslateCat)


class TranslateProduct(TranslationOptions):
    fields = (
        "name",
        "short_description",
        "description",
        "specifications",
        "features",
        "seo_title",
        "seo_description",
        "tags",
    )
    # Only the default language is mandatory — modeltranslation otherwise
    # makes every language variant optional (blank=True) regardless of the
    # original field's own blank/null attributes.
    required_languages = {"en": ["name", "description"]}
translator.register(Product, TranslateProduct)