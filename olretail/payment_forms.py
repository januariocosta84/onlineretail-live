from django import forms
from django.db.models import Avg, Count
from django.utils.translation import gettext_lazy as _

from olretail.models import City, Courier, CourierVerificationStatus, Municipality, Seller, SellerBankAccount
from .payment_models import Cart, Order, Dispute, DeliveryUpdate, PaymentMethod
from .subscription_models import SubscriptionPlan
from .validators import validate_iban, validate_image_size, validate_swift_code


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


class PaymentProofForm(forms.Form):
    """Required receipt + reference number when a buyer confirms they've
    sent a bank/mobile transfer — see payment_views.mark_payment_sent.
    Capturing structured evidence up front (not just a click) is what lets
    a later seller denial or admin review have something concrete to look
    at, and lets duplicate/mismatched claims get auto-flagged before anyone
    has to notice by hand."""

    payment_proof = forms.ImageField(
        required=True,
        widget=forms.ClearableFileInput(attrs={'class': 'form-control-file', 'capture': 'environment', 'accept': 'image/*'}),
        label=_("Payment receipt / screenshot"),
        error_messages={'required': _('A receipt or screenshot of the transfer is required.')},
    )
    payment_reference = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('e.g. the bank transaction/reference number')}),
        label=_("Transfer reference number"),
        error_messages={'required': _('Enter the reference/transaction number shown on your transfer.')},
    )
    payment_amount_claimed = forms.DecimalField(
        max_digits=13,
        decimal_places=2,
        required=True,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        label=_("Amount you sent"),
    )

    def clean_payment_proof(self):
        photo = self.cleaned_data.get('payment_proof')
        validate_image_size(photo)
        return photo


class PaymentDenialForm(forms.Form):
    """Seller's reason when they deny having received a buyer's claimed
    bank/mobile transfer — see payment_views.deny_payment_received. Shown
    to the buyer and to the admin who reviews the resulting dispute, so a
    bare "no" isn't accepted."""

    reason = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 3,
            'class': 'form-control',
            'placeholder': _("Explain why you haven't received this payment..."),
        }),
        label=_("Reason"),
        error_messages={'required': _('A reason is required — this is shown to the buyer and reviewed by an administrator.')},
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
    """Supplementary payment notes shown alongside a seller's structured
    Bank Accounts (see BankAccountForm/SellerBankAccount) — mobile money
    details, or anything else that doesn't fit the bank-account fields."""

    class Meta:
        model = Seller
        fields = ['payment_instructions']
        widgets = {
            'payment_instructions': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': _('e.g. Mobile money: +670 7712 1173, or any other payment notes for buyers'),
                'class': 'form-control'
            }),
        }
        labels = {
            'payment_instructions': _('Additional payment notes (optional)'),
        }


class BankAccountForm(forms.ModelForm):
    """One of a seller's bank accounts — add one, list them, delete one at
    a time (same shape as MenuCategoryForm/olretail.views.menu_categories).
    `seller` is stamped onto the instance in the view, not exposed here."""

    class Meta:
        model = SellerBankAccount
        fields = ['account_holder_name', 'bank_name', 'account_number', 'swift_code', 'iban']
        widgets = {
            'account_holder_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('e.g. Jose Costa')}),
            'bank_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('e.g. BNU Timor-Leste')}),
            'account_number': forms.TextInput(attrs={'class': 'form-control'}),
            'swift_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Optional')}),
            'iban': forms.TextInput(attrs={'class': 'form-control', 'placeholder': _('Optional')}),
        }
        labels = {
            'account_holder_name': _('Account Holder Name'),
            'bank_name': _('Bank Name'),
            'account_number': _('Account Number'),
            'swift_code': _('SWIFT Code'),
            'iban': _('IBAN'),
        }
        help_texts = {
            'swift_code': _('Optional — only needed for international transfers, if your bank has one.'),
            'iban': _('Optional — only needed for international transfers, if your bank uses one.'),
        }

    def clean_swift_code(self):
        value = self.cleaned_data.get('swift_code', '').strip().upper()
        validate_swift_code(value)
        return value

    def clean_iban(self):
        value = self.cleaned_data.get('iban', '').strip().upper().replace(' ', '')
        validate_iban(value)
        return value


class SellerBusinessIdentityForm(forms.ModelForm):
    """Lets a non-individual seller fix their business/registration and
    director details after registration (the registration form only
    collects Business Name + Contact Person up front — everything else
    lives here). Changing company_name/company_tin/company_address/
    business_registration_number reverts an already-verified seller to
    pending review (see olretail/payment_views.py seller_business_identity)."""

    class Meta:
        model = Seller
        fields = [
            'company_name', 'business_registration_number', 'company_tin',
            'company_address', 'company_bank_account',
            'director_name', 'director_id_number', 'director_phone', 'director_email',
        ]
        widgets = {
            'company_name': forms.TextInput(attrs={'class': 'form-control'}),
            'business_registration_number': forms.TextInput(attrs={'class': 'form-control'}),
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
            'business_registration_number': _('Business Registration Number'),
            'company_tin': _('TIN (Tax Identification Number)'),
            'company_address': _('Business address (legacy — use Location below instead)'),
            'company_bank_account': _('Bank account'),
            'director_name': _('Director name'),
            'director_id_number': _('Director ID / TIN number'),
            'director_phone': _('Director phone number'),
            'director_email': _('Director email'),
        }


class SellerContactForm(forms.ModelForm):
    """Who buyers/admins should contact, and (optionally) a WhatsApp number
    different from the seller's phone number."""

    class Meta:
        model = Seller
        fields = ['contact_person_name', 'whatsapp_number_override']
        widgets = {
            'contact_person_name': forms.TextInput(attrs={'class': 'form-control'}),
            'whatsapp_number_override': forms.TextInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'contact_person_name': _('Contact Person'),
            'whatsapp_number_override': _('WhatsApp Number'),
        }
        help_texts = {
            'whatsapp_number_override': _('Leave blank to use your phone number for WhatsApp.'),
        }


class SellerLocationForm(forms.ModelForm):
    """Business address, Timor-Leste municipality, and optional GPS
    coordinates — separate from the personal/delivery address collected at
    signup."""

    class Meta:
        model = Seller
        fields = [
            'municipality', 'administrative_post', 'suco', 'aldeia',
            'full_address', 'gps_latitude', 'gps_longitude',
        ]
        widgets = {
            'municipality': forms.Select(attrs={'class': 'form-control'}),
            'administrative_post': forms.TextInput(attrs={'class': 'form-control'}),
            'suco': forms.TextInput(attrs={'class': 'form-control'}),
            'aldeia': forms.TextInput(attrs={'class': 'form-control'}),
            'full_address': forms.TextInput(attrs={'class': 'form-control'}),
            'gps_latitude': forms.NumberInput(attrs={'class': 'form-control', 'step': 'any'}),
            'gps_longitude': forms.NumberInput(attrs={'class': 'form-control', 'step': 'any'}),
        }
        labels = {
            'municipality': _('Municipality'),
            'administrative_post': _('Administrative Post'),
            'suco': _('Suco'),
            'aldeia': _('Aldeia'),
            'full_address': _('Full Address'),
            'gps_latitude': _('GPS Latitude'),
            'gps_longitude': _('GPS Longitude'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['municipality'].queryset = Municipality.objects.all()
        self.fields['municipality'].empty_label = _('Select municipality')


class SellerBrandingForm(forms.ModelForm):
    """Logo and cover image shown on the seller's listings/profile."""

    class Meta:
        model = Seller
        fields = ['logo', 'cover_image']
        widgets = {
            'logo': forms.ClearableFileInput(attrs={'class': 'form-control-file', 'accept': 'image/*'}),
            'cover_image': forms.ClearableFileInput(attrs={'class': 'form-control-file', 'accept': 'image/*'}),
        }
        labels = {
            'logo': _('Business Logo'),
            'cover_image': _('Business Cover Image'),
        }

    def clean_logo(self):
        photo = self.cleaned_data.get('logo')
        if photo:
            validate_image_size(photo)
        return photo

    def clean_cover_image(self):
        photo = self.cleaned_data.get('cover_image')
        if photo:
            validate_image_size(photo)
        return photo


class SellerOperationsForm(forms.ModelForm):
    """Opening/closing hours and delivery/pickup/cash-on-delivery
    availability — informational this phase, not wired into checkout."""

    class Meta:
        model = Seller
        fields = [
            'opening_time', 'closing_time',
            'delivery_available', 'pickup_available', 'cash_on_delivery_available',
        ]
        widgets = {
            'opening_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'closing_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'delivery_available': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'pickup_available': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'cash_on_delivery_available': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'opening_time': _('Opening Hours'),
            'closing_time': _('Closing Hours'),
            'delivery_available': _('Delivery Available'),
            'pickup_available': _('Pickup Available'),
            'cash_on_delivery_available': _('Cash on Delivery Available'),
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
