from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _

from olretail.models import SellerType

from .roles import ACCOUNT_TYPE_CHOICES, ROLE_BUYER, ROLE_BUYER_SELLER, ROLE_SELLER


class RegistrationForm(UserCreationForm):
    """Registration with role selection, uniqueness checks and password validation."""

    account_type = forms.ChoiceField(
        choices=ACCOUNT_TYPE_CHOICES,
        initial=ROLE_BUYER,
        widget=forms.RadioSelect(attrs={"class": "custom-control-input"}),
        label=_("Account type"),
    )
    seller_type = forms.ChoiceField(
        choices=SellerType.choices,
        initial=SellerType.INDIVIDUAL,
        required=False,
        widget=forms.RadioSelect(attrs={"class": "custom-control-input"}),
        label=_("Seller type"),
    )
    company_name = forms.CharField(
        max_length=200,
        required=False,
        label=_("Company name"),
        widget=forms.TextInput(attrs={"placeholder": _("Acme Trading Lda")}),
    )
    company_tin = forms.CharField(
        max_length=50,
        required=False,
        label=_("TIN (Tax Identification Number)"),
        widget=forms.TextInput(attrs={"placeholder": _("e.g. 123456789")}),
    )
    company_address = forms.CharField(
        max_length=255,
        required=False,
        label=_("Company address"),
        widget=forms.TextInput(attrs={"placeholder": _("Street, City, Region")}),
    )
    company_bank_account = forms.CharField(
        max_length=100,
        required=False,
        label=_("Bank account"),
        widget=forms.TextInput(attrs={"placeholder": _("Bank name, account number, account holder")}),
    )
    first_name = forms.CharField(
        max_length=150,
        label=_("First name"),
        widget=forms.TextInput(attrs={"placeholder": _("John")}),
    )
    last_name = forms.CharField(
        max_length=150,
        label=_("Last name"),
        widget=forms.TextInput(attrs={"placeholder": _("Doe")}),
    )
    email = forms.EmailField(
        label=_("Email address"),
        widget=forms.EmailInput(attrs={"placeholder": _("you@example.com")}),
    )
    mobile = forms.CharField(
        max_length=40,
        label=_("Phone number"),
        widget=forms.TextInput(attrs={"placeholder": _("7012345 or +670 7012345")}),
    )
    address = forms.CharField(
        max_length=255,
        label=_("Address"),
        widget=forms.TextInput(attrs={"placeholder": _("Street, City, Region")}),
    )

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "username", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add Bootstrap classes
        for field in self.fields.values():
            if not isinstance(field.widget, forms.RadioSelect):
                field.widget.attrs.setdefault("class", "form-control")
        
        # Customize password fields with better help text
        self.fields["password1"].widget = forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": _("Enter a strong password")}
        )
        self.fields["password2"].widget = forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": _("Confirm password")}
        )
        self.fields["username"].widget = forms.TextInput(
            attrs={"class": "form-control", "placeholder": _("choose_a_username")}
        )

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_("An account with this email address already exists."))
        return email

    def clean(self):
        cleaned_data = super().clean()
        account_type = cleaned_data.get("account_type")
        if account_type not in (ROLE_SELLER, ROLE_BUYER_SELLER):
            return cleaned_data

        cleaned_data["seller_type"] = cleaned_data.get("seller_type") or SellerType.INDIVIDUAL
        if cleaned_data["seller_type"] != SellerType.COMPANY:
            return cleaned_data

        required_fields = {
            "company_name": _("Company name is required for a company seller account."),
            "company_tin": _("TIN is required for a company seller account."),
            "company_address": _("Company address is required for a company seller account."),
            "company_bank_account": _("Bank account is required for a company seller account."),
        }
        for field_name, message in required_fields.items():
            if not cleaned_data.get(field_name):
                self.add_error(field_name, message)
        return cleaned_data
