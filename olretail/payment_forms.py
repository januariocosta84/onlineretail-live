from django import forms
from django.utils.translation import gettext_lazy as _

from olretail.models import Courier, Seller
from .payment_models import Cart, Order, Dispute, DeliveryUpdate, PaymentMethod
from .subscription_models import SubscriptionPlan


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


class DeliveryProofForm(forms.Form):
    """Required photo proof when marking an order delivered."""

    photo = forms.ImageField(
        required=True,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control-file', 'capture': 'environment', 'accept': 'image/*'}),
        label=_("Delivery Photo"),
        error_messages={'required': _('A delivery photo is required to confirm delivery.')},
    )


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
