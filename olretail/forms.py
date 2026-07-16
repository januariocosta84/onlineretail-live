from django import forms
from django.utils.translation import gettext_lazy as _

from .models import SERVICE_CATEGORY_SLUG, Category, Comment, Product
from .validators import validate_image_size


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = (
            "name",
            "price",
            "category",
            "country",
            "item_location",
            "quantity",
            "condition",
            "size",
            "pieces_per_unit",
            "units_per_box",
            "description",
            "product_image",
            "product_image_2",
            "product_image_3",
        )
        labels = {
            "name": _("Product name"),
            "price": _("Price"),
            "category": _("Category"),
            "country": _("Country"),
            "item_location": _("City"),
            "quantity": _("Quantity"),
            "condition": _("Condition"),
            "size": _("Size"),
            "pieces_per_unit": _("Pieces per unit"),
            "units_per_box": _("Units per box"),
            "description": _("Description"),
            "product_image": _("Main image"),
            "product_image_2": _("Extra image 1"),
            "product_image_3": _("Extra image 2"),
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }
        help_texts = {
            "quantity": _("Set to 0 when the product is sold out."),
            "size": _("Optional — e.g. L, 42, 500ml"),
            "pieces_per_unit": _("Optional — e.g. 12 pens in a pack"),
            "units_per_box": _("Optional — e.g. 24 packs in a box"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].empty_label = _("Select category")
        self.fields["country"].empty_label = _("Select country")
        self.fields["item_location"].empty_label = _("Select city")
        for name, field in self.fields.items():
            css = "form-control"
            if isinstance(field.widget, forms.Select):
                css = "browser-default custom-select"
            elif isinstance(field.widget, forms.ClearableFileInput):
                css = "form-control-file"
            field.widget.attrs.setdefault("class", css)
        # The quantity/condition inputs are disabled client-side for a
        # service category, so nothing is posted for them — don't require
        # what the page never let the seller fill in.
        if self._submitted_category_is_service():
            self.fields["quantity"].required = False
            self.fields["condition"].required = False

    def _submitted_category_is_service(self):
        if not self.is_bound:
            return False
        category_id = self.data.get("category")
        if not category_id:
            return False
        return Category.objects.filter(pk=category_id, slug=SERVICE_CATEGORY_SLUG).exists()

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
        if category and category.slug == SERVICE_CATEGORY_SLUG:
            cleaned_data["quantity"] = cleaned_data.get("quantity") or 1
            cleaned_data["condition"] = cleaned_data.get("condition") or "New"
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


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ("commenter_name", "body")
        labels = {"commenter_name": _("Your name"), "body": _("Comment")}
        widgets = {
            "commenter_name": forms.TextInput(attrs={"class": "form-control"}),
            "body": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }
