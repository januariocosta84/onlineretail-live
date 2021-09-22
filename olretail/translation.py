from django.conf import settings
from django.utils.translation import gettext_lazy
from modeltranslation.translator import translator, register, TranslationOptions

from .models import Category

class TranslateCat(TranslationOptions):
    fields=('title',)
translator.register(Category, TranslateCat)