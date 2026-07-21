from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from modeltranslation.utils import build_localized_fieldname

from .models import (
    NO_CONDITION_QUANTITY_CATEGORY_SLUGS,
    RESTAURANT_CATEGORY_SLUG,
    Category,
    Comment,
    MenuCategory,
    Product,
)
from .validators import validate_image_size

# Base (language-less) names of Product's translatable fields — see
# olretail/translation.py. Each expands to one real form field per
# MODELTRANSLATION_LANGUAGES entry (e.g. "name" -> name_en/name_tet/...).
TRANSLATABLE_PRODUCT_FIELDS = (
    "name",
    "short_description",
    "description",
    "specifications",
    "features",
    "seo_title",
    "seo_description",
    "tags",
)
# Fields long enough to deserve a textarea + full-width layout in the
# language tabs, and how many rows each gets.
_TEXTAREA_PRODUCT_FIELDS = {"description": 4, "specifications": 4, "features": 4}

_PRODUCT_FIELD_LABELS = {
    "name": _("Product name"),
    "short_description": _("Short description"),
    "description": _("Full description"),
    "specifications": _("Specifications"),
    "features": _("Features"),
    "seo_title": _("SEO title"),
    "seo_description": _("SEO description"),
    "tags": _("Tags"),
}


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = (
            "price",
            "category",
            "country",
            "item_location",
            "quantity",
            "condition",
            "size",
            "pieces_per_unit",
            "units_per_box",
            "menu_category",
            "is_available",
            "prep_time_minutes",
            "product_image",
            "product_image_2",
            "product_image_3",
        ) + tuple(
            build_localized_fieldname(base, lang)
            for base in TRANSLATABLE_PRODUCT_FIELDS
            for lang in settings.MODELTRANSLATION_LANGUAGES
        )
        labels = {
            "price": _("Price"),
            "category": _("Category"),
            "country": _("Country"),
            "item_location": _("City"),
            "quantity": _("Quantity"),
            "condition": _("Condition"),
            "size": _("Size"),
            "pieces_per_unit": _("Pieces per unit"),
            "units_per_box": _("Units per box"),
            "menu_category": _("Menu section"),
            "is_available": _("Available"),
            "prep_time_minutes": _("Prep time (minutes)"),
            "product_image": _("Main image"),
            "product_image_2": _("Extra image 1"),
            "product_image_3": _("Extra image 2"),
            **{
                build_localized_fieldname(base, lang): label
                for base, label in _PRODUCT_FIELD_LABELS.items()
                for lang in settings.MODELTRANSLATION_LANGUAGES
            },
        }
        widgets = {
            **{
                build_localized_fieldname(base, lang): forms.Textarea(attrs={"rows": rows})
                for base, rows in _TEXTAREA_PRODUCT_FIELDS.items()
                for lang in settings.MODELTRANSLATION_LANGUAGES
            },
        }
        help_texts = {
            "quantity": _("Set to 0 when the product is sold out."),
            "size": _("Optional — e.g. L, 42, 500ml"),
            "pieces_per_unit": _("Optional — e.g. 12 pens in a pack"),
            "units_per_box": _("Optional — e.g. 24 packs in a box"),
            "menu_category": _("Which section of your menu this item belongs to"),
            "prep_time_minutes": _("Optional — e.g. 20"),
        }

    def __init__(self, *args, seller=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._seller = seller
        self.fields["category"].empty_label = _("Select category")
        self.fields["country"].empty_label = _("Select country")
        self.fields["item_location"].empty_label = _("Select city")
        self.fields["menu_category"].queryset = (
            MenuCategory.objects.filter(seller=seller) if seller else MenuCategory.objects.none()
        )
        self.fields["menu_category"].empty_label = _("Select menu section")
        self.fields["is_available"].required = False
        for name, field in self.fields.items():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "browser-default custom-select"
            elif isinstance(field.widget, forms.ClearableFileInput):
                css = "form-control-file"
            elif isinstance(field.widget, forms.CheckboxInput):
                css = "form-check-input"
            field.widget.attrs.setdefault("class", css)
        # The quantity/condition inputs are disabled client-side for a
        # service or restaurant category, so nothing is posted for them —
        # don't require what the page never let the seller fill in.
        if self._hides_quantity_condition():
            self.fields["quantity"].required = False
            self.fields["condition"].required = False

    @property
    def translated_field_names(self):
        """Flat list of every per-language field name (name_en, name_tet,
        ...) — used by the template to skip them in the generic field loop
        so they're only rendered once, inside the language tabs."""
        return [
            build_localized_fieldname(base, lang)
            for base in TRANSLATABLE_PRODUCT_FIELDS
            for lang in settings.MODELTRANSLATION_LANGUAGES
        ]

    def language_tabs(self):
        """One entry per configured language, each carrying the bound
        fields for that language in a fixed order — drives the tabbed
        language switcher in product_form.html."""
        tabs = []
        for lang_code, lang_label in settings.LANGUAGES:
            fields = [
                {
                    "base": base,
                    "bound": self[build_localized_fieldname(base, lang_code)],
                    "full_width": base in _TEXTAREA_PRODUCT_FIELDS,
                }
                for base in TRANSLATABLE_PRODUCT_FIELDS
            ]
            tabs.append({"code": lang_code, "label": lang_label, "fields": fields})
        return tabs

    def _submitted_category_slug(self):
        if not self.is_bound:
            return None
        category_id = self.data.get("category")
        if not category_id:
            return None
        category = Category.objects.filter(pk=category_id).first()
        return category.slug if category else None

    def _hides_quantity_condition(self):
        return self._submitted_category_slug() in NO_CONDITION_QUANTITY_CATEGORY_SLUGS

    def clean_price(self):
        price = self.cleaned_data["price"]
        if price is not None and price <= 0:
            raise forms.ValidationError(_("Price must be greater than zero."))
        return price

    # Quantity 0 is valid: it marks the product as sold out while keeping the
    # listing visible; PositiveIntegerField already rejects negatives.

    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get("category")
        if category and category.slug in NO_CONDITION_QUANTITY_CATEGORY_SLUGS:
            cleaned_data["quantity"] = cleaned_data.get("quantity") or 1
            cleaned_data["condition"] = cleaned_data.get("condition") or "New"
        if not category or category.slug != RESTAURANT_CATEGORY_SLUG:
            # Menu section / availability only make sense for restaurant
            # listings — the fields are disabled client-side for every other
            # category, so nothing is posted for them; don't let a stray
            # False/None linger if the seller switches category away from
            # Restaurant after picking one.
            cleaned_data["menu_category"] = None
            cleaned_data["is_available"] = True
        return cleaned_data

    def clean_product_image(self):
        image = self.cleaned_data.get("product_image")
        validate_image_size(image)
        return image

    def clean_product_image_2(self):
        image = self.cleaned_data.get("product_image_2")
        validate_image_size(image)
        return image

    def clean_product_image_3(self):
        image = self.cleaned_data.get("product_image_3")
        validate_image_size(image)
        return image


class MenuCategoryForm(forms.ModelForm):
    """A restaurant's own menu section (Breakfast, Lunch, Drinks, ...)."""

    class Meta:
        model = MenuCategory
        fields = ("name", "display_order")
        labels = {"name": _("Section name"), "display_order": _("Display order")}
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": _("e.g. Breakfast")}),
            "display_order": forms.NumberInput(attrs={"class": "form-control"}),
        }
        help_texts = {
            "display_order": _("Lower numbers show first on the menu."),
        }


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ("commenter_name", "body")
        labels = {"commenter_name": _("Your name"), "body": _("Comment")}
        widgets = {
            "commenter_name": forms.TextInput(attrs={"class": "form-control"}),
            "body": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }
