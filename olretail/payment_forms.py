from django import forms
from django.db.models import Avg, Count
from django.utils.translation import gettext_lazy as _

from olretail.models import City, Courier, CourierVerificationStatus, Seller
from .payment_models import Cart, Order, Dispute, DeliveryUpdate, PaymentMethod
from .subscription_models import SubscriptionPlan
from .validators import validate_image_size


class CheckoutForm(forms.Form):
    """Delivery information for checkout."""

    payment_method = forms.ChoiceField(
        choices=PaymentMethod.choices,
        initial=PaymentMethod.STRIPE,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        label=_("Payment Method"),
    )

    delivery_address = forms.CharField(
        max_length=255,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': _('Street, City, Region'),
            'class': 'form-control'
        }),
        label=_("Delivery Address"),
        help_text=_("Where should we deliver your order?")
    )

    delivery_city = forms.ModelChoiceField(
        queryset=City.objects.select_related('country'),
        empty_label=_("Select city"),
        widget=forms.Select(attrs={'class': 'form-control'}),
        label=_("Delivery City"),
        help_text=_("Couriers are matched to this city"),
    )

    delivery_phone = forms.CharField(
        max_length=40,
        widget=forms.TextInput(attrs={
            'placeholder': _('7012345 or +670 7012345'),
            'class': 'form-control'
        }),
        label=_("Delivery Phone"),
        help_text=_("Seller will contact you on this number")
    )
    
    buyer_notes = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': _('Any special instructions? (Optional)'),
            'class': 'form-control'
        }),
        label=_("Special Instructions"),
        help_text=_("E.g., 'Please knock loudly' or 'Leave at door'")
    )

    # Only required when payment_method == SIMULATED_BANK (see clean()) —
    # optional at the field level so it doesn't block Stripe/manual-transfer
    # checkouts, which never render this input.
    bank_account_number = forms.CharField(
        max_length=34,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': _('e.g. SIM-0001-SUCCESS'),
            'class': 'form-control'
        }),
        label=_("Bank Account Number"),
        help_text=_("The account you're paying from."),
    )

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('payment_method') == PaymentMethod.SIMULATED_BANK and not cleaned_data.get('bank_account_number'):
            self.add_error('bank_account_number', _('Enter the account number you\'re paying from.'))
        return cleaned_data


class DisputeForm(forms.ModelForm):
    """Form for buyer to open dispute."""
    
    class Meta:
        model = Dispute
        fields = ['reason', 'description', 'buyer_evidence']
        widgets = {
            'reason': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={
                'rows': 4,
                'placeholder': _('Describe what happened...'),
                'class': 'form-control'
            }),
            'buyer_evidence': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': _('Upload photos or describe the issue'),
                'class': 'form-control'
            }),
        }
        labels = {
            'reason': _('Reason for dispute'),
            'description': _('Description'),
            'buyer_evidence': _('Evidence (photos, messages, etc.)'),
        }


class SellerDisputeResponseForm(forms.Form):
    """Form for seller to respond to dispute."""
    
    seller_response = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 4,
            'placeholder': _('Provide your response with evidence...'),
            'class': 'form-control'
        }),
        label=_("Your Response"),
        help_text=_("You have 3 days to respond. Explain your side and provide evidence.")
    )


class ShipOrderForm(forms.Form):
    """Courier/tracking details a seller enters when marking an order shipped."""

    courier_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': _('e.g. Timor Post, local courier name'),
            'class': 'form-control form-control-sm'
        }),
        label=_("Courier / Delivery Service"),
    )
    tracking_number = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': _('Tracking number, if any'),
            'class': 'form-control form-control-sm'
        }),
        label=_("Tracking Number"),
    )
    assigned_courier = forms.ModelChoiceField(
        queryset=Courier.objects.select_related('user'),
        required=False,
        empty_label=_("No courier account (self-delivery / informal courier)"),
        widget=forms.Select(attrs={'class': 'form-control form-control-sm'}),
        label=_("Assign Courier"),
    )

    def __init__(self, *args, order=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Only verified couriers are assignable — an unverified one has no
        # ID/deposit on file yet, so there's nothing to trust them with.
        queryset = Courier.objects.select_related('user').filter(
            verification_status=CourierVerificationStatus.VERIFIED
        ).annotate(avg_rating=Avg('ratings__score'), rating_count=Count('ratings'))
        if order is not None and order.delivery_city_id is not None:
            # Only narrow the list when at least one courier actually
            # covers that city — an empty dropdown (besides "no courier
            # account") would be worse than showing everyone.
            matched = queryset.filter(service_cities=order.delivery_city_id)
            if matched.exists():
                queryset = matched
        self.fields['assigned_courier'].queryset = queryset
        self.fields['assigned_courier'].label_from_instance = self._courier_label

    @staticmethod
    def _courier_label(courier):
        if courier.rating_count:
            return _("%(name)s (★ %(avg).1f, %(count)d rating(s))") % {
                'name': courier.get_name, 'avg': courier.avg_rating, 'count': courier.rating_count,
            }
        return _("%(name)s (no ratings yet)") % {'name': courier.get_name}


class DeliveryProofForm(forms.Form):
    """Required photo proof when marking an order delivered."""

    photo = forms.ImageField(
        required=True,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control-file', 'capture': 'environment', 'accept': 'image/*'}),
        label=_("Delivery Photo"),
        error_messages={'required': _('A delivery photo is required to confirm delivery.')},
    )

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        validate_image_size(photo)
        return photo


class CourierVerificationForm(forms.Form):
    """ID document photo a courier submits for admin review before they can
    be assigned any deliveries (see Courier.verification_status)."""

    id_document = forms.ImageField(
        widget=forms.ClearableFileInput(attrs={'class': 'form-control-file', 'accept': 'image/*'}),
        label=_("ID Document Photo"),
        error_messages={'required': _('Please upload a photo of your ID document.')},
    )

    def clean_id_document(self):
        photo = self.cleaned_data.get('id_document')
        validate_image_size(photo)
        return photo


class DeliveryUpdateForm(forms.ModelForm):
    """A single free-text status update posted by the seller."""

    class Meta:
        model = DeliveryUpdate
        fields = ['note']
        widgets = {
            'note': forms.TextInput(attrs={
                'placeholder': _("e.g. 'Left Dili warehouse, arriving Baucau tomorrow'"),
                'class': 'form-control form-control-sm'
            }),
        }
        labels = {
            'note': _('Status update'),
        }


class SubscriptionRequestForm(forms.Form):
    """Seller reports a plan payment made directly to the platform; an
    admin confirms it before it activates."""

    plan = forms.ChoiceField(
        choices=[(SubscriptionPlan.MONTHLY, SubscriptionPlan.MONTHLY.label),
                 (SubscriptionPlan.YEARLY, SubscriptionPlan.YEARLY.label)],
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        label=_("Choose a plan"),
    )
    payment_reference = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 3,
            'class': 'form-control',
            'placeholder': _("e.g. Bank transfer ref #123, paid 14 Jul 2026"),
        }),
        label=_("Payment reference"),
        help_text=_("Tell the admin how and when you paid, so they can confirm it."),
    )


class SellerPaymentInstructionsForm(forms.ModelForm):
    """Bank/mobile money details a seller shows buyers who pay by transfer."""

    class Meta:
        model = Seller
        fields = ['payment_instructions']
        widgets = {
            'payment_instructions': forms.Textarea(attrs={
                'rows': 5,
                'placeholder': _('e.g. BNU Timor-Leste, Account: 1234567, Name: Jose Costa'),
                'class': 'form-control'
            }),
        }
        labels = {
            'payment_instructions': _('Payment details for buyers'),
        }


class SellerCompanyInfoForm(forms.ModelForm):
    """Lets a company or restaurant seller fix their business and director
    details after registration (the registration form is the only other
    place these are collected)."""

    class Meta:
        model = Seller
        fields = [
            'company_name', 'company_tin', 'company_address', 'company_bank_account',
            'director_name', 'director_id_number', 'director_phone', 'director_email',
        ]
        widgets = {
            'company_name': forms.TextInput(attrs={'class': 'form-control'}),
            'company_tin': forms.TextInput(attrs={'class': 'form-control'}),
            'company_address': forms.TextInput(attrs={'class': 'form-control'}),
            'company_bank_account': forms.TextInput(attrs={'class': 'form-control'}),
            'director_name': forms.TextInput(attrs={'class': 'form-control'}),
            'director_id_number': forms.TextInput(attrs={'class': 'form-control'}),
            'director_phone': forms.TextInput(attrs={'class': 'form-control'}),
            'director_email': forms.EmailInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'company_name': _('Business name'),
            'company_tin': _('TIN (Tax Identification Number)'),
            'company_address': _('Business address'),
            'company_bank_account': _('Bank account'),
            'director_name': _('Director name'),
            'director_id_number': _('Director ID / TIN number'),
            'director_phone': _('Director phone number'),
            'director_email': _('Director email'),
        }


class SellerVerificationForm(forms.Form):
    """Business registration document a company seller submits for admin
    review — a trust badge for buyers, not a requirement to sell."""

    business_document = forms.ImageField(
        widget=forms.ClearableFileInput(attrs={'class': 'form-control-file', 'accept': 'image/*'}),
        label=_("Business Registration Document"),
        error_messages={'required': _('Please upload a photo of your business registration document.')},
    )

    def clean_business_document(self):
        photo = self.cleaned_data.get('business_document')
        validate_image_size(photo)
        return photo
