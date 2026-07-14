from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Comment, Product


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

    def clean_price(self):
        price = self.cleaned_data["price"]
        if price is not None and price <= 0:
            raise forms.ValidationError(_("Price must be greater than zero."))
        return price

    # Quantity 0 is valid: it marks the product as sold out while keeping the
    # listing visible; PositiveIntegerField already rejects negatives.


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ("commenter_name", "body")
        labels = {"commenter_name": _("Your name"), "body": _("Comment")}
        widgets = {
            "commenter_name": forms.TextInput(attrs={"class": "form-control"}),
            "body": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }
